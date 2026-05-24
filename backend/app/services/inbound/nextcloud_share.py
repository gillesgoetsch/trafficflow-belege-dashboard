"""Nextcloud public-share inbound connector.

A Nextcloud share link looks like:
    https://cloud.example.com/s/TOKEN
    https://cloud.example.com/index.php/s/TOKEN

The public WebDAV endpoint is:
    https://cloud.example.com/public.php/webdav/

Auth: HTTP Basic with TOKEN as username, empty password.
Listing: PROPFIND with Depth: infinity (or 1, then recurse).
Download: GET the file path under that WebDAV root.

This is fully read-only and works without any OAuth/app registration.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote
from xml.etree import ElementTree as ET

import httpx

from app.core.logging import get_logger

from .base import InboundConnector, RemoteFile

logger = get_logger(__name__)


_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tiff", ".tif"}


def _parse_share_url(url: str) -> tuple[str, str]:
    """Extract (origin, share_token) from a Nextcloud share URL.

    Accepts:
      https://cloud.host/s/TOKEN
      https://cloud.host/index.php/s/TOKEN
      https://cloud.host/s/TOKEN/  (trailing slash)
      https://cloud.host/s/TOKEN?<query>
    """
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid share URL: {url!r}")
    m = re.search(r"/(?:index\.php/)?s/([A-Za-z0-9]+)/?", parsed.path)
    if not m:
        raise ValueError(f"No share token in URL: {url!r}")
    token = m.group(1)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, token


class NextcloudShareConnector(InboundConnector):
    def __init__(self, share_url: str, password: str | None = None):
        self.origin, self.token = _parse_share_url(share_url)
        self.password = password or ""
        self.webdav_root = f"{self.origin}/public.php/webdav/"

    def _client(self) -> httpx.AsyncClient:
        # Basic auth: token as username, optional password
        return httpx.AsyncClient(
            base_url=self.webdav_root,
            auth=(self.token, self.password),
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    async def test(self) -> tuple[bool, str | None]:
        try:
            async with self._client() as c:
                r = await c.request("PROPFIND", "/", headers={"Depth": "0"})
            if r.status_code in (200, 207):
                return True, None
            return False, f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    async def list_files(self) -> list[RemoteFile]:
        """PROPFIND with Depth: infinity. Falls back to recursive Depth: 1
        if the server refuses infinite depth (Nextcloud allows it on shares
        in recent versions).
        """
        files: list[RemoteFile] = []
        async with self._client() as c:
            # Try infinity first
            r = await c.request("PROPFIND", "/", headers={"Depth": "infinity"})
            if r.status_code == 403:
                # Some configs disable infinity; recurse manually with Depth 1
                return await self._list_recursive(c, "/")
            if r.status_code not in (200, 207):
                raise RuntimeError(f"Nextcloud PROPFIND failed: {r.status_code} {r.text[:200]}")
            files = self._parse_multistatus(r.text)
        return [f for f in files if self._is_supported(f.filename)]

    async def _list_recursive(self, c: httpx.AsyncClient, path: str) -> list[RemoteFile]:
        out: list[RemoteFile] = []
        r = await c.request("PROPFIND", path, headers={"Depth": "1"})
        if r.status_code not in (200, 207):
            raise RuntimeError(f"Nextcloud PROPFIND failed: {r.status_code}")
        items = self._parse_multistatus(r.text)
        for it in items:
            if it.content_type == "httpd/unix-directory":
                # subdirectory — recurse
                sub = it.remote_id
                if sub.rstrip("/") == path.rstrip("/"):
                    continue
                out.extend(await self._list_recursive(c, sub))
            else:
                out.append(it)
        return [f for f in out if self._is_supported(f.filename)]

    def _is_supported(self, name: str) -> bool:
        if not name:
            return False
        lower = name.lower()
        return any(lower.endswith(ext) for ext in _FILE_EXTS)

    def _parse_multistatus(self, body: str) -> list[RemoteFile]:
        ns = {"d": "DAV:"}
        out: list[RemoteFile] = []
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            logger.warning("nextcloud.parse_error", error=str(e))
            return []
        for resp in root.findall("d:response", ns):
            href_el = resp.find("d:href", ns)
            if href_el is None or not href_el.text:
                continue
            href = unquote(href_el.text)
            # href is like /public.php/webdav/Folder/file.pdf
            # Strip the webdav prefix to get the file path relative to the share
            rel = re.sub(r"^.*?/public\.php/webdav/", "/", href) or "/"
            # filename = last non-empty path segment
            segments = [s for s in rel.split("/") if s]
            filename = segments[-1] if segments else ""
            # find props
            prop = resp.find("d:propstat/d:prop", ns)
            ctype = None
            size = None
            mtime = None
            if prop is not None:
                ct_el = prop.find("d:getcontenttype", ns)
                if ct_el is not None and ct_el.text:
                    ctype = ct_el.text
                sz_el = prop.find("d:getcontentlength", ns)
                if sz_el is not None and sz_el.text:
                    try:
                        size = int(sz_el.text)
                    except ValueError:
                        pass
                lm_el = prop.find("d:getlastmodified", ns)
                if lm_el is not None and lm_el.text:
                    try:
                        # RFC 1123 format
                        from email.utils import parsedate_to_datetime
                        mtime = parsedate_to_datetime(lm_el.text)
                        if mtime.tzinfo is None:
                            mtime = mtime.replace(tzinfo=timezone.utc)
                    except Exception:  # noqa: BLE001
                        pass
                rt_el = prop.find("d:resourcetype/d:collection", ns)
                if rt_el is not None:
                    ctype = "httpd/unix-directory"
            out.append(RemoteFile(
                remote_id=rel, filename=filename, size=size, mtime=mtime,
                content_type=ctype,
            ))
        return out

    async def download_file(self, remote_id: str) -> bytes:
        # remote_id is the path relative to webdav root (starts with /)
        async with self._client() as c:
            r = await c.get(remote_id.lstrip("/"))
            r.raise_for_status()
            return r.content
