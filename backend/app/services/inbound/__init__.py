"""Inbound cloud-folder connectors.

Read-only providers that watch a share link / mount for new files and
push their bytes into the receipt ingestion pipeline.
"""
from __future__ import annotations

from app.db.models import InboundFolderType

from .base import InboundConnector, RemoteFile
from .gdrive_share import GDriveShareConnector
from .local_mount import LocalMountConnector
from .nextcloud_share import NextcloudShareConnector
from .onedrive_share import OneDriveShareConnector

__all__ = [
    "InboundConnector",
    "RemoteFile",
    "build_connector",
]


def build_connector(type_: InboundFolderType, share_url: str, config: dict | None = None) -> InboundConnector:
    config = config or {}
    if type_ == InboundFolderType.nextcloud_share:
        return NextcloudShareConnector(share_url, password=config.get("password"))
    if type_ == InboundFolderType.onedrive_share:
        return OneDriveShareConnector(share_url)
    if type_ == InboundFolderType.gdrive_share:
        return GDriveShareConnector(share_url)
    if type_ == InboundFolderType.local_mount:
        return LocalMountConnector(share_url)
    raise ValueError(f"Unknown inbound folder type: {type_}")
