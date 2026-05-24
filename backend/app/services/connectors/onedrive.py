"""OneDrive connector via Microsoft Graph API.

Auth: OAuth refresh_token captured in the /api/connectors/onedrive/callback
endpoint. We never persist plaintext tokens — only Fernet-encrypted.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import settings
from app.db.models import ConnectorMode
from app.services.connectors.base import Connector, ReceiptToUpload, SyncResult


GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


class OneDriveConnector(Connector):
    type_name = "onedrive"

    @classmethod
    def config_schema(cls) -> dict[str, Any]:
        return {
            "fields": [
                {"name": "folder_path", "label": "OneDrive folder", "type": "string",
                 "required": True, "placeholder": "/Belege"},
                {"name": "refresh_token", "label": "Refresh token", "type": "string",
                 "required": True, "secret": True, "readonly": True},
            ],
            "oauth": True,
            "authorize_endpoint": "/api/connectors/onedrive/authorize",
        }

    async def _access_token(self) -> str:
        # If cached and unexpired, reuse; else refresh.
        exp = self.config.get("expires_at")
        if exp and self.config.get("access_token") and datetime.utcnow().timestamp() < float(exp):
            return self.config["access_token"]
        rt = self.config.get("refresh_token")
        if not rt:
            raise RuntimeError("OneDrive connector missing refresh_token; reauthorize.")
        data = {
            "client_id": settings.onedrive_client_id,
            "client_secret": settings.onedrive_client_secret,
            "refresh_token": rt,
            "grant_type": "refresh_token",
            "scope": "offline_access Files.ReadWrite User.Read",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(TOKEN_URL, data=data)
            r.raise_for_status()
            j = r.json()
        token = j["access_token"]
        # update in-memory; caller may persist if needed
        self.config["access_token"] = token
        self.config["expires_at"] = (datetime.utcnow() + timedelta(seconds=int(j.get("expires_in", 3600)) - 60)).timestamp()
        if j.get("refresh_token"):
            self.config["refresh_token"] = j["refresh_token"]
        return token

    def _resolve_target_path(self, receipt: ReceiptToUpload) -> str:
        folder = (self.config.get("folder_path") or "/Belege").lstrip("/")
        d = receipt.document_date
        parts = [folder, str(receipt.organization_id)]
        if d:
            parts.extend([str(d.year), f"{d.month:02d}"])
        return "/".join(parts + [receipt.filename])

    async def upload(
        self,
        receipt: ReceiptToUpload,
        *,
        mode: ConnectorMode = ConnectorMode.live,
        auto_book: bool = False,
    ) -> SyncResult:
        if mode == ConnectorMode.off:
            return SyncResult(ok=False, error="connector mode=off", mode=mode)

        path = self._resolve_target_path(receipt)
        url = f"{GRAPH}/me/drive/root:/{path}:/content"
        payload = {"action": "PUT", "url": url, "filename": receipt.filename}

        if mode == ConnectorMode.dry_run:
            return SyncResult(
                ok=True, mode=mode, request_payload=payload,
            )

        token = await self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/pdf"}
        with open(receipt.file_path, "rb") as f:
            data = f.read()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.put(url, content=data, headers=headers)
            if resp.status_code >= 400:
                return SyncResult(
                    ok=False,
                    error=f"OneDrive {resp.status_code}: {resp.text[:200]}",
                    mode=ConnectorMode.live,
                    request_payload=payload,
                    response_status_code=resp.status_code,
                    response_payload={"text": resp.text[:1000]},
                )
            j = resp.json()
            return SyncResult(
                ok=True, external_id=j.get("id"),
                mode=ConnectorMode.live,
                request_payload=payload,
                response_payload=j,
                response_status_code=resp.status_code,
            )

    async def test(self) -> bool:
        try:
            token = await self._access_token()
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{GRAPH}/me", headers={"Authorization": f"Bearer {token}"})
                return r.status_code == 200
        except Exception:
            return False
