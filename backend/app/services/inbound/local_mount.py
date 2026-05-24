"""Local-mount inbound connector.

Reads from a directory mounted on the API/worker container. The
share_url field carries the path. Useful for rsync/Syncthing/NFS
setups where you don't want to expose the folder over HTTP.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .base import InboundConnector, RemoteFile

_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tiff", ".tif"}


class LocalMountConnector(InboundConnector):
    def __init__(self, share_url: str):
        # share_url is just the local path here
        self.root = Path(share_url.strip()).resolve()

    async def test(self) -> tuple[bool, str | None]:
        if not self.root.exists():
            return False, f"Path does not exist: {self.root}"
        if not self.root.is_dir():
            return False, f"Not a directory: {self.root}"
        return True, None

    async def list_files(self) -> list[RemoteFile]:
        out: list[RemoteFile] = []
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            if not any(p.name.lower().endswith(ext) for ext in _FILE_EXTS):
                continue
            stat = p.stat()
            rel = str(p.relative_to(self.root))
            out.append(RemoteFile(
                remote_id=rel,
                filename=p.name,
                size=stat.st_size,
                mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                content_type=None,
            ))
        return out

    async def download_file(self, remote_id: str) -> bytes:
        p = (self.root / remote_id).resolve()
        # safety: don't escape the root
        if self.root not in p.parents and p != self.root:
            raise RuntimeError(f"Path traversal blocked: {remote_id!r}")
        return p.read_bytes()
