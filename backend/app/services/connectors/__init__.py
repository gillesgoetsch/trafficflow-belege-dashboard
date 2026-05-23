"""Connector registry — pluggable file destinations."""
from __future__ import annotations

from app.services.connectors.base import Connector, ConnectorConfigSchema, SyncResult
from app.services.connectors.bexio import BexioConnector
from app.services.connectors.local import LocalConnector
from app.services.connectors.onedrive import OneDriveConnector

REGISTRY: dict[str, type[Connector]] = {
    "local": LocalConnector,
    "onedrive": OneDriveConnector,
    "bexio": BexioConnector,
}


def get_connector_class(name: str) -> type[Connector]:
    if name not in REGISTRY:
        raise ValueError(f"Unknown connector type: {name}")
    return REGISTRY[name]


__all__ = [
    "Connector",
    "ConnectorConfigSchema",
    "SyncResult",
    "REGISTRY",
    "get_connector_class",
]
