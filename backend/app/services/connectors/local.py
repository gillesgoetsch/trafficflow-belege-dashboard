"""Local filesystem connector — already writes there, this is for additional
mirror paths if the user wants (e.g. a synced Dropbox folder)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

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

    async def upload(self, receipt: ReceiptToUpload) -> SyncResult:
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
        target_dir = base / sub
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / receipt.filename
        shutil.copy2(receipt.file_path, target)
        return SyncResult(ok=True, external_id=str(target))

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
