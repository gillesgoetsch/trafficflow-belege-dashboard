"""Google Drive public-share inbound connector.

A Drive folder share URL contains the folder ID:
    https://drive.google.com/drive/folders/FOLDER_ID[?usp=sharing]

Drive v3 API endpoints:
    GET https://www.googleapis.com/drive/v3/files
        ?q='FOLDER_ID' in parents and trashed=false
        &fields=files(id,name,size,modifiedTime,mimeType,parents),nextPageToken
        &key=API_KEY
        &supportsAllDrives=true&includeItemsFromAllDrives=true

    GET https://www.googleapis.com/drive/v3/files/FILE_ID?alt=media&key=API_KEY

Auth: a Google Cloud API key with Drive API enabled is sufficient for
PUBLIC shares ("Anyone with the link can view"). The user only ever
pastes the share URL.

If GOOGLE_API_KEY is missing in env, this connector reports a clear
error from test() so the UI can prompt the operator to set it.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx

from app.config import settings
from app.core.logging import get_logger

from .base import InboundConnector, RemoteFile

logger = get_logger(__name__)

_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tiff", ".tif"}
_FOLDER_MIME = "application/vnd.google-apps.folder"


def _extract_folder_id(url: str) -> str:
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    # also handle ?id= query
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"No folder id in URL: {url!r}")


def _api_key() -> str | None:
    return getattr(settings, "google_api_key", None)


def _is_supported(name: str) -> bool:
    if not name:
        return False
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _FILE_EXTS)


def _parse_mtime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


class GDriveShareConnector(InboundConnector):
    def __init__(self, share_url: str):
        self.folder_id = _extract_folder_id(share_url)

    async def test(self) -> tuple[bool, str | None]:
        key = _api_key()
        if not key:
            return False, "GOOGLE_API_KEY not configured on server"
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(
                    "https://www.googleapis.com/drive/v3/files",
                    params={
                        "q": f"'{self.folder_id}' in parents and trashed=false",
                        "fields": "files(id,name)",
                        "key": key,
                        "supportsAllDrives": "true",
                        "includeItemsFromAllDrives": "true",
                        "pageSize": 1,
                    },
                )
            if r.status_code == 200:
                return True, None
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    async def list_files(self) -> list[RemoteFile]:
        key = _api_key()
        if not key:
            raise RuntimeError("GOOGLE_API_KEY not configured on server")
        out: list[RemoteFile] = []
        async with httpx.AsyncClient(timeout=60) as c:
            await self._walk(c, key, self.folder_id, out)
        return [f for f in out if _is_supported(f.filename)]

    async def _walk(self, c: httpx.AsyncClient, key: str, folder_id: str, out: list[RemoteFile]) -> None:
        page_token: str | None = None
        while True:
            params = {
                "q": f"'{folder_id}' in parents and trashed=false",
                "fields": "files(id,name,size,modifiedTime,mimeType),nextPageToken",
                "key": key,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token
            r = await c.get("https://www.googleapis.com/drive/v3/files", params=params)
            r.raise_for_status()
            data = r.json()
            for it in data.get("files", []):
                if it.get("mimeType") == _FOLDER_MIME:
                    await self._walk(c, key, it["id"], out)
                else:
                    out.append(RemoteFile(
                        remote_id=it["id"],
                        filename=it.get("name", ""),
                        size=int(it["size"]) if it.get("size") else None,
                        mtime=_parse_mtime(it.get("modifiedTime")),
                        content_type=it.get("mimeType"),
                    ))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    async def download_file(self, remote_id: str) -> bytes:
        key = _api_key()
        if not key:
            raise RuntimeError("GOOGLE_API_KEY not configured on server")
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.get(
                f"https://www.googleapis.com/drive/v3/files/{remote_id}",
                params={"alt": "media", "key": key, "supportsAllDrives": "true"},
                follow_redirects=True,
            )
            r.raise_for_status()
            return r.content
