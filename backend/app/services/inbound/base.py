"""Inbound cloud-folder connector base.

Every provider implements `list_files()` (cheap remote listing) and
`download_file()` (fetch raw bytes for a specific remote_id). The worker
loop diffs the listing against `inbound_files` (folder_id, remote_id) and
downloads only what's new.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RemoteFile:
    remote_id: str  # provider-stable identifier (path/ID/etag)
    filename: str
    size: int | None = None
    mtime: datetime | None = None
    content_type: str | None = None


class InboundConnector(ABC):
    """Read-only listing + download for a public/share-link cloud folder."""

    @abstractmethod
    async def list_files(self) -> list[RemoteFile]:
        """List all files (recursively or not) reachable from the configured root."""

    @abstractmethod
    async def download_file(self, remote_id: str) -> bytes:
        """Fetch raw bytes for one file."""

    @abstractmethod
    async def test(self) -> tuple[bool, str | None]:
        """Quick reachability/auth check. Returns (ok, error_message)."""
