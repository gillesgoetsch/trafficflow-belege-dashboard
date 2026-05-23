"""Connector ABC: upload(receipt) + test() + config schema for the UI."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar


@dataclass
class SyncResult:
    ok: bool
    external_id: str | None = None
    error: str | None = None


@dataclass
class ConnectorConfigSchema:
    fields: list[dict[str, Any]]  # [{name, label, type, required, secret}]


@dataclass
class ReceiptToUpload:
    receipt_id: int
    organization_id: int
    file_path: Path
    filename: str
    document_date: Any
    provider: str | None
    client: str | None
    amount: Any
    currency: str | None


class Connector(ABC):
    type_name: ClassVar[str] = "base"

    def __init__(self, config: dict[str, Any]):
        self.config = config or {}

    @classmethod
    @abstractmethod
    def config_schema(cls) -> dict[str, Any]: ...

    @abstractmethod
    async def upload(self, receipt: ReceiptToUpload) -> SyncResult: ...

    @abstractmethod
    async def test(self) -> bool: ...
