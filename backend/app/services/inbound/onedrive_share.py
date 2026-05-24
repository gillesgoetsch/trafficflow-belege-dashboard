"""OneDrive public-share inbound connector.

A OneDrive share URL gets encoded into a Graph shareId:
    shareId = "u!" + base64url(URL).rstrip("=")

Then:
    GET https://graph.microsoft.com/v1.0/shares/{shareId}/driveItem
    GET https://graph.microsoft.com/v1.0/shares/{shareId}/driveItem/children
    GET https://graph.microsoft.com/v1.0/shares/{shareId}/driveItem/items/{id}/content

Auth: app-only access token via client_credentials flow with the
Microsoft app registration (reused from the outbound onedrive connector).
The Files.Read.All Graph permission is sufficient.
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger

from .base import InboundConnector, RemoteFile

logger = get_logger(__name__)


_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tiff", ".tif"}


def encode_share_id(url: str) -> str:
    enc = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + enc


async def _get_app_token() -> str:
    tenant = getattr(settings, "ms_tenant_id", None) or "common"
    client_id = getattr(settings, "ms_client_id", None) or getattr(settings, "onedrive_client_id", None)
    client_secret = getattr(settings, "ms_client_secret", None) or getattr(settings, "onedrive_client_secret", None)
    if not (client_id and client_secret):
        raise RuntimeError("OneDrive share requires MS_CLIENT_ID + MS_CLIENT_SECRET in env")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


def _is_supported(name: str) -> bool:
    if not name:
        return False
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _FILE_EXTS)


def _parse_mtime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # OneDrive uses ISO8601 with Z
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


class OneDriveShareConnector(InboundConnector):
    def __init__(self, share_url: str):
        self.share_url = share_url.strip()
        self.share_id = encode_share_id(self.share_url)
        self._token: str | None = None

    async def _auth_header(self) -> dict[str, str]:
        if not self._token:
            self._token = await _get_app_token()
        return {"Authorization": f"Bearer {self._token}"}

    async def test(self) -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(
                    f"https://graph.microsoft.com/v1.0/shares/{self.share_id}/driveItem",
                    headers=await self._auth_header(),
                )
            if r.status_code == 200:
                return True, None
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    async def list_files(self) -> list[RemoteFile]:
        out: list[RemoteFile] = []
        async with httpx.AsyncClient(timeout=60) as c:
            await self._walk(c, "root", out)
        return [f for f in out if _is_supported(f.filename)]

    async def _walk(self, c: httpx.AsyncClient, item_id: str, out: list[RemoteFile]) -> None:
        """Recursive list. item_id='root' addresses the shared root."""
        headers = await self._auth_header()
        if item_id == "root":
            url = f"https://graph.microsoft.com/v1.0/shares/{self.share_id}/driveItem/children"
        else:
            url = f"https://graph.microsoft.com/v1.0/shares/{self.share_id}/driveItem/items/{item_id}/children"
        while url:
            r = await c.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            for it in data.get("value", []):
                if "folder" in it:
                    await self._walk(c, it["id"], out)
                else:
                    out.append(RemoteFile(
                        remote_id=it["id"],
                        filename=it.get("name", ""),
                        size=it.get("size"),
                        mtime=_parse_mtime(it.get("lastModifiedDateTime")),
                        content_type=(it.get("file") or {}).get("mimeType"),
                    ))
            url = data.get("@odata.nextLink")

    async def download_file(self, remote_id: str) -> bytes:
        headers = await self._auth_header()
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.get(
                f"https://graph.microsoft.com/v1.0/shares/{self.share_id}/driveItem/items/{remote_id}/content",
                headers=headers,
                follow_redirects=True,
            )
            r.raise_for_status()
            return r.content
