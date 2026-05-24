"""Connector ABC: upload(receipt) + test() + config schema for the UI.

The `upload()` signature accepts a `mode` keyword (off/dry_run/live) so every
connector can record what it would have done in dry-run without doing it.
`SyncResult` also carries `request_payload` and `response_payload` so the
pipeline can persist them on the sync_target for the audit/inspector UI.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from app.db.models import ConnectorMode


@dataclass
class SyncResult:
    ok: bool
    external_id: str | None = None
    error: str | None = None
    mode: ConnectorMode | None = None
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    response_status_code: int | None = None


@dataclass
class ConnectorConfigSchema:
    fields: list[dict[str, Any]]  # [{name, label, type, required, secret}]


@dataclass
class ReceiptToUpload:
    receipt_id: int
    organization_id: int
    file_path: Path
    filename: str
    document_date: Any = None
    due_date: Any = None
    provider: str | None = None
    client: str | None = None
    amount: Any = None
    currency: str | None = None
    invoice_number: str | None = None
    vat_rate: float | None = None
    vat_amount: float | None = None
    account_code: str | None = None
    vat_code: str | None = None
    notes: str | None = None


class Connector(ABC):
    type_name: ClassVar[str] = "base"

    def __init__(self, config: dict[str, Any]):
        self.config = config or {}

    @classmethod
    @abstractmethod
    def config_schema(cls) -> dict[str, Any]: ...

    @abstractmethod
    async def upload(
        self,
        receipt: ReceiptToUpload,
        *,
        mode: ConnectorMode = ConnectorMode.live,
        auto_book: bool = False,
    ) -> SyncResult: ...

    @abstractmethod
    async def test(self) -> bool: ...
