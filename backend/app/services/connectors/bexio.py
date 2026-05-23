"""Bexio connector — uploads receipts as bookkeeping documents.

Bexio API: https://docs.bexio.com — uses API token (no OAuth needed for token auth).
We POST the file to the document inbox / file API.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.services.connectors.base import Connector, ReceiptToUpload, SyncResult


BEXIO_API = "https://api.bexio.com/2.0"


class BexioConnector(Connector):
    type_name = "bexio"

    @classmethod
    def config_schema(cls) -> dict[str, Any]:
        return {
            "fields": [
                {"name": "api_token", "label": "API token", "type": "string",
                 "required": True, "secret": True},
                {"name": "inbox_path", "label": "Inbox folder (optional)", "type": "string",
                 "required": False, "placeholder": "Belege/2026"},
            ]
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.get('api_token', '')}",
            "Accept": "application/json",
        }

    async def upload(self, receipt: ReceiptToUpload) -> SyncResult:
        with open(receipt.file_path, "rb") as f:
            file_bytes = f.read()
        files = {"file": (receipt.filename, file_bytes, "application/pdf")}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{BEXIO_API}/files", headers=self._headers(), files=files)
            if r.status_code >= 400:
                return SyncResult(ok=False, error=f"Bexio {r.status_code}: {r.text[:200]}")
            data = r.json()
            return SyncResult(ok=True, external_id=str(data.get("id") or data.get("uuid") or ""))

    async def test(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{BEXIO_API}/company_profile", headers=self._headers())
                return r.status_code == 200
        except Exception:
            return False
