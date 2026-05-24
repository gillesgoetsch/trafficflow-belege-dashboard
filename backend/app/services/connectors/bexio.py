"""Bexio connector — Beleg auto-fill (kb_bill creation + PDF attachment).

Three modes:
- live    : POST /3.0/files (upload PDF) → POST /2.0/kb_bill (create draft)
            → if auto_book, POST /2.0/kb_bill/{id}/bookings
- dry_run : read-only supplier search + build the would-be payload, never POST
- off     : handled by pipeline (this code is never reached when mode==off)

Auth: Personal Access Token (PAT). See connector config_schema.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import httpx

from app.db.models import ConnectorMode
from app.services.connectors.base import (
    Connector,
    ReceiptToUpload,
    SyncResult,
)


BEXIO_BASE = "https://api.bexio.com"
FILES_URL = f"{BEXIO_BASE}/3.0/files"
BILLS_URL = f"{BEXIO_BASE}/2.0/kb_bill"
CONTACT_SEARCH_URL = f"{BEXIO_BASE}/2.0/contact/search"
COMPANY_URL = f"{BEXIO_BASE}/2.0/company_profile"


class BexioConnector(Connector):
    type_name = "bexio"

    @classmethod
    def config_schema(cls) -> dict[str, Any]:
        return {
            "fields": [
                {"name": "api_token", "label": "Personal Access Token (PAT)",
                 "type": "string", "required": True, "secret": True},
                {"name": "default_account_code", "label": "Default account code",
                 "type": "string", "required": False, "placeholder": "6510"},
                {"name": "default_vat_code", "label": "Default VAT code",
                 "type": "string", "required": False, "placeholder": "VST077"},
                {"name": "default_currency", "label": "Default currency",
                 "type": "string", "required": False, "placeholder": "CHF"},
            ]
        }

    # -- HTTP helpers ---------------------------------------------------------

    def _json_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.get('api_token', '')}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _file_headers(self) -> dict[str, str]:
        # multipart — let httpx set Content-Type
        return {
            "Authorization": f"Bearer {self.config.get('api_token', '')}",
            "Accept": "application/json",
        }

    # -- payload assembly (pure) ---------------------------------------------

    def build_payload(
        self,
        receipt: ReceiptToUpload,
        supplier_id: int | None = None,
        file_ids: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Build the kb_bill request body. Pure function — safe in dry-run."""
        currency = (
            receipt.currency
            or self.config.get("default_currency")
            or "CHF"
        ).upper()
        account_code = (
            receipt.account_code
            or self.config.get("default_account_code")
            or None
        )
        vat_code = (
            receipt.vat_code
            or self.config.get("default_vat_code")
            or None
        )
        amount = float(receipt.amount or 0)

        doc_date = _to_iso_date(receipt.document_date) or _today_iso()
        due_date = _to_iso_date(receipt.due_date) or doc_date

        title_parts = [p for p in (receipt.provider, receipt.invoice_number) if p]
        title = " / ".join(title_parts) or receipt.filename

        position: dict[str, Any] = {
            "amount": f"{amount:.2f}",
            "description": title,
        }
        if account_code:
            position["account_code"] = account_code
        if vat_code:
            position["vat_code"] = vat_code

        body: dict[str, Any] = {
            "supplier_id": supplier_id,
            "document_no": receipt.invoice_number,
            "vendor_ref": receipt.invoice_number,
            "title": title,
            "currency_code": currency,
            "bill_date": doc_date,
            "due_date": due_date,
            "positions": [position],
            "file_ids": list(file_ids or []),
        }
        return body

    # -- main entry point -----------------------------------------------------

    async def upload(
        self,
        receipt: ReceiptToUpload,
        *,
        mode: ConnectorMode = ConnectorMode.live,
        auto_book: bool = False,
    ) -> SyncResult:
        if mode == ConnectorMode.off:
            return SyncResult(ok=False, error="connector mode=off", mode=mode)

        if mode == ConnectorMode.dry_run:
            return await self._dry_run(receipt, auto_book=auto_book)

        return await self._live(receipt, auto_book=auto_book)

    # -- dry-run path ---------------------------------------------------------

    async def _dry_run(
        self,
        receipt: ReceiptToUpload,
        *,
        auto_book: bool,
    ) -> SyncResult:
        supplier_id: int | None = None
        supplier_match: dict[str, Any] = {"query": receipt.provider, "result": "skipped"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if receipt.provider:
                    supplier_id, supplier_match = await self._search_supplier(
                        receipt.provider, client=client,
                    )
        except Exception as e:  # noqa: BLE001
            supplier_match = {"query": receipt.provider, "result": "error", "error": str(e)}

        payload = self.build_payload(receipt, supplier_id=supplier_id)
        return SyncResult(
            ok=True,
            external_id=None,
            mode=ConnectorMode.dry_run,
            request_payload={
                "would_upload_file": receipt.filename,
                "supplier_search": supplier_match,
                "kb_bill": payload,
                "would_auto_book": auto_book,
            },
            response_payload=None,
            response_status_code=None,
        )

    # -- live path ------------------------------------------------------------

    async def _live(
        self,
        receipt: ReceiptToUpload,
        *,
        auto_book: bool,
    ) -> SyncResult:
        supplier_id: int | None = None
        supplier_match: dict[str, Any] = {"query": receipt.provider, "result": "skipped"}
        file_info: dict[str, Any] = {}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # 1. supplier search (read-only — never fatal)
                if receipt.provider:
                    try:
                        supplier_id, supplier_match = await self._search_supplier(
                            receipt.provider, client=client,
                        )
                    except Exception as e:  # noqa: BLE001
                        supplier_match = {
                            "query": receipt.provider, "result": "error", "error": str(e),
                        }

                # 2. upload file
                with open(receipt.file_path, "rb") as f:
                    file_bytes = f.read()
                files = {"file": (receipt.filename, file_bytes, "application/pdf")}
                r_file = await client.post(
                    FILES_URL, headers=self._file_headers(), files=files,
                )
                if r_file.status_code >= 400:
                    return SyncResult(
                        ok=False,
                        error=f"Bexio file upload {r_file.status_code}: {r_file.text[:300]}",
                        mode=ConnectorMode.live,
                        request_payload={
                            "step": "file_upload",
                            "filename": receipt.filename,
                            "supplier_search": supplier_match,
                        },
                        response_payload=_try_json(r_file),
                        response_status_code=r_file.status_code,
                    )
                file_info = _try_json(r_file) or {}
                file_id = file_info.get("id") or file_info.get("uuid")

                # 3. create kb_bill
                payload = self.build_payload(
                    receipt, supplier_id=supplier_id,
                    file_ids=[file_id] if file_id else [],
                )
                r_bill = await client.post(
                    BILLS_URL,
                    headers=self._json_headers(),
                    content=json.dumps(payload, default=str),
                )
                if r_bill.status_code >= 400:
                    return SyncResult(
                        ok=False,
                        error=f"Bexio kb_bill {r_bill.status_code}: {r_bill.text[:300]}",
                        mode=ConnectorMode.live,
                        request_payload={
                            "supplier_search": supplier_match,
                            "file_upload_response": file_info,
                            "kb_bill": payload,
                        },
                        response_payload=_try_json(r_bill),
                        response_status_code=r_bill.status_code,
                    )
                bill_data = _try_json(r_bill) or {}
                bill_id = bill_data.get("id")

                # 4. optionally auto-book
                book_response: dict[str, Any] | None = None
                if auto_book and bill_id:
                    r_book = await client.post(
                        f"{BILLS_URL}/{bill_id}/bookings",
                        headers=self._json_headers(),
                        content=json.dumps({}, default=str),
                    )
                    book_response = _try_json(r_book)
                    if r_book.status_code >= 400:
                        # Bill exists but booking failed — report success-with-warning
                        return SyncResult(
                            ok=True,
                            external_id=str(bill_id),
                            error=(
                                f"Bill {bill_id} created, but auto-book failed "
                                f"({r_book.status_code}). Open Bexio to book manually."
                            ),
                            mode=ConnectorMode.live,
                            request_payload={
                                "supplier_search": supplier_match,
                                "kb_bill": payload,
                                "auto_book_attempted": True,
                            },
                            response_payload={
                                "bill": bill_data,
                                "book_error": book_response,
                            },
                            response_status_code=r_bill.status_code,
                        )

                return SyncResult(
                    ok=True,
                    external_id=str(bill_id) if bill_id else None,
                    mode=ConnectorMode.live,
                    request_payload={
                        "supplier_search": supplier_match,
                        "kb_bill": payload,
                        "auto_book": auto_book,
                    },
                    response_payload={
                        "bill": bill_data,
                        "book": book_response,
                    },
                    response_status_code=r_bill.status_code,
                )
        except Exception as e:  # noqa: BLE001
            return SyncResult(
                ok=False,
                error=f"Bexio exception: {e}",
                mode=ConnectorMode.live,
                request_payload={"supplier_search": supplier_match, "file": file_info},
            )

    # -- contact search -------------------------------------------------------

    async def _search_supplier(
        self,
        name: str,
        *,
        client: httpx.AsyncClient,
    ) -> tuple[int | None, dict[str, Any]]:
        """POST /2.0/contact/search by company name. Returns (contact_id, log)."""
        if not name:
            return None, {"query": name, "result": "no_query"}
        body = [{"field": "name_1", "value": name, "criteria": "like"}]
        r = await client.post(
            CONTACT_SEARCH_URL,
            headers=self._json_headers(),
            content=json.dumps(body),
        )
        if r.status_code >= 400:
            return None, {
                "query": name, "result": "error",
                "status": r.status_code, "body": r.text[:200],
            }
        data = _try_json(r)
        if isinstance(data, list) and data:
            first = data[0] or {}
            return first.get("id"), {
                "query": name, "result": "match",
                "match": {
                    "id": first.get("id"),
                    "name_1": first.get("name_1"),
                    "name_2": first.get("name_2"),
                },
            }
        return None, {"query": name, "result": "no_match"}

    # -- test -----------------------------------------------------------------

    async def test(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    COMPANY_URL,
                    headers={
                        "Authorization": f"Bearer {self.config.get('api_token', '')}",
                        "Accept": "application/json",
                    },
                )
                return r.status_code == 200
        except Exception:
            return False


# -- helpers -----------------------------------------------------------------


def _to_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        # already a date-like string; trust caller
        return value[:10]
    return None


def _today_iso() -> str:
    return date.today().isoformat()


def _try_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:1000]}
