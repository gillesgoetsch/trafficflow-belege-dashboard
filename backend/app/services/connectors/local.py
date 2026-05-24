"""Local filesystem connector — already writes there, this is for additional
mirror paths if the user wants (e.g. a synced Dropbox folder)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.db.models import ConnectorMode
from app.services.connectors.base import Connector, ReceiptToUpload, SyncResult


class LocalConnector(Connector):
    type_name = "local"

    @classmethod
    def config_schema(cls) -> dict[str, Any]:
        return {
            "fields": [
                {"name": "base_path", "label": "Base directory", "type": "string",
                 "required": True, "placeholder": "/data/local-mirror"},
                {"name": "subpath_template", "label": "Subdirectory template", "type": "string",
                 "required": False, "placeholder": "{org}/{year}/{month}"},
            ]
        }

    def _resolve_target(self, receipt: ReceiptToUpload) -> Path:
        base = Path(self.config.get("base_path") or "/data/local-mirror")
        tmpl = self.config.get("subpath_template") or "{org}/{year}/{month}"
        d = receipt.document_date
        sub = tmpl.format(
            org=receipt.organization_id,
            year=getattr(d, "year", "0000") if d else "0000",
            month=f"{getattr(d, 'month', 1):02d}" if d else "01",
            provider=(receipt.provider or "Unknown"),
            client=(receipt.client or "General"),
        )
        return base / sub / receipt.filename

    async def upload(
        self,
        receipt: ReceiptToUpload,
        *,
        mode: ConnectorMode = ConnectorMode.live,
        auto_book: bool = False,
    ) -> SyncResult:
        if mode == ConnectorMode.off:
            return SyncResult(ok=False, error="connector mode=off", mode=mode)

        target = self._resolve_target(receipt)
        payload = {
            "action": "copy",
            "source": str(receipt.file_path),
            "target": str(target),
        }
        if mode == ConnectorMode.dry_run:
            return SyncResult(
                ok=True, mode=mode, request_payload=payload,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(receipt.file_path, target)
        return SyncResult(
            ok=True, external_id=str(target),
            mode=ConnectorMode.live, request_payload=payload,
        )

    async def test(self) -> bool:
        base = Path(self.config.get("base_path") or "/data/local-mirror")
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".belege-test"
            probe.write_text("ok")
            probe.unlink()
            return True
        except Exception:
            return False
