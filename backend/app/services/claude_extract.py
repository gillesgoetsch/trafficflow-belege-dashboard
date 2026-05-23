"""Claude-based receipt metadata extraction.

This replaces the fragile regex-based extractor with a single LLM call that
reads the actual PDF (or image) and returns structured fields. Anthropic's
Documents API supports PDFs natively — no client-side OCR needed.

We use Sonnet for accuracy. Cost per receipt: ~$0.005, negligible at our
volume and a huge win on accuracy.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from dateutil import parser as dateparser

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


_PROMPT = """You are extracting structured metadata from a receipt / invoice / Rechnung for an SMB bookkeeping system.

Read the document carefully and return STRICT JSON with this exact shape:

{
  "is_receipt": true | false,
  "vendor": "Vendor / company name issuing the invoice" | null,
  "vendor_slug": "lowercase-kebab-slug for the vendor" | null,
  "customer_hint": "If the customer/recipient/billing name on the document mentions an org, brand, or person, return it verbatim. Otherwise null.",
  "document_date": "YYYY-MM-DD" | null,   // DATE OF ISSUE (Rechnungsdatum / Issue Date / Date of Invoice)
  "due_date": "YYYY-MM-DD" | null,         // when payment is OWED (Fälligkeitsdatum / Due Date / Payable by)
  "total_amount": "1234.56" | null,        // total including VAT, decimal point, NO thousands separator
  "currency": "CHF" | "EUR" | "USD" | "GBP" | ...,
  "vat_rate": "8.1" | "2.6" | "0" | null,  // percent
  "vat_amount": "12.34" | null,
  "invoice_number": "INV-..." | null,
  "language": "de" | "en" | "fr" | "it" | null,
  "notes": "one-line plain summary, e.g. 'Meta Ads subscription Apr 2026'"
}

CRITICAL rules:
- document_date is the DATE OF ISSUE — the day the invoice was created/issued. Labels:
  "Rechnungsdatum", "Invoice Date", "Issue Date", "Date of issue", "Datum",
  "Erstellt am", "Date", "Bill Date". This is the field that drives accounting periods.
- due_date is the date PAYMENT IS DUE. Labels: "Fälligkeitsdatum", "Fällig am",
  "Due Date", "Payment Due", "Zahlbar bis", "Date d'échéance".
  Many receipts (already-paid CC charges, instant transactions) have NO due date —
  return null in that case. Do not invent one. Do not copy the issue date here.
- If you only see ONE date on the document and it's labeled as an issue/invoice date
  (or unlabeled but clearly the invoice header date), put it in document_date and
  leave due_date null.
- total_amount is the GROSS / Brutto / total-including-VAT amount the customer paid.
- If you see both Netto and Brutto, return Brutto. If only one total is given, return that.
- Ignore stray numbers that appear inside the vendor's product names (e.g. "Porsche 911", "Boeing 747").
- The decimal separator in the OUTPUT must be a dot. Convert "119,10" → "119.10".
- Do not include the currency symbol in total_amount.
- If the document is not a receipt/invoice (marketing email, contract, shipping confirmation
  without amounts), set is_receipt to false and leave other fields null.

Return ONLY the JSON object — no preamble, no markdown fences."""


@dataclass
class ClaudeReceipt:
    is_receipt: bool
    vendor: str | None
    vendor_slug: str | None
    customer_hint: str | None
    document_date: str | None    # date of issue (Rechnungsdatum)
    due_date: str | None         # Fälligkeitsdatum
    total_amount: Decimal | None
    currency: str | None
    vat_rate: Decimal | None
    vat_amount: Decimal | None
    invoice_number: str | None
    language: str | None
    notes: str | None
    raw: dict


def _to_decimal(v: Any) -> Decimal | None:
    if v in (None, "", "null"):
        return None
    try:
        s = str(v).replace(" ", "").replace("'", "")
        if "," in s and "." in s:
            # If both present, comma is thousands sep
            s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(v: str | None) -> str | None:
    if not v:
        return None
    try:
        return dateparser.parse(v).date().isoformat()
    except Exception:
        return None


def _coerce(data: dict) -> ClaudeReceipt:
    return ClaudeReceipt(
        is_receipt=bool(data.get("is_receipt")),
        vendor=data.get("vendor"),
        vendor_slug=data.get("vendor_slug"),
        customer_hint=data.get("customer_hint"),
        document_date=_parse_date(data.get("document_date")),
        due_date=_parse_date(data.get("due_date")),
        total_amount=_to_decimal(data.get("total_amount")),
        currency=(data.get("currency") or "").upper() or None,
        vat_rate=_to_decimal(data.get("vat_rate")),
        vat_amount=_to_decimal(data.get("vat_amount")),
        invoice_number=data.get("invoice_number"),
        language=data.get("language"),
        notes=data.get("notes"),
        raw=data,
    )


def _parse_response(text: str) -> dict:
    """Extract a JSON object from Claude's reply, tolerantly."""
    if not text:
        return {}
    text = text.strip()
    # Strip code fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


async def _vision_fallback_pdf(pdf_path: Path, client: AsyncAnthropic) -> ClaudeReceipt:
    """Render the PDF's first page to PNG and send to Claude Vision.

    Used when the Documents API can't read the PDF (image-only scans usually).
    """
    from playwright.async_api import async_playwright
    png_bytes = b""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            try:
                ctx = await browser.new_context(viewport={"width": 1240, "height": 1754})
                page = await ctx.new_page()
                await page.goto(pdf_path.absolute().as_uri(), wait_until="load", timeout=20000)
                await page.wait_for_timeout(1500)
                png_bytes = await page.screenshot(full_page=True, type="png")
            finally:
                await browser.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("claude_extract.vision_render_failed", path=str(pdf_path), error=str(e))
        return ClaudeReceipt(False, None, None, None, None, None, None, None, None, None, None, None, None, {"error": "render_failed"})

    if not png_bytes:
        return ClaudeReceipt(False, None, None, None, None, None, None, None, None, None, None, None, None, {"error": "no_png"})

    msg = await client.messages.create(
        model=settings.ocr_model,
        max_tokens=900,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                  "data": base64.standard_b64encode(png_bytes).decode()}},
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    return _coerce(_parse_response(text))


async def extract_from_pdf(pdf_path: Path) -> ClaudeReceipt:
    if not settings.anthropic_api_key:
        return ClaudeReceipt(False, None, None, None, None, None, None, None, None, None, None, None, None, {"error": "no_api_key"})
    pdf_bytes = pdf_path.read_bytes()
    b64 = base64.standard_b64encode(pdf_bytes).decode()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        msg = await client.messages.create(
            model=settings.ocr_model,
            max_tokens=900,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        result = _coerce(_parse_response(text))
        if result.is_receipt or result.total_amount is not None or result.vendor:
            return result
        logger.info("claude_extract.pdf_empty_falling_back_to_vision", path=str(pdf_path))
    except Exception as e:  # noqa: BLE001
        logger.warning("claude_extract.pdf_failed_falling_back_to_vision", path=str(pdf_path), error=str(e))

    # Render to image and try Vision (handles image-only scanned PDFs)
    return await _vision_fallback_pdf(pdf_path, client)


async def extract_from_image(image_path: Path) -> ClaudeReceipt:
    if not settings.anthropic_api_key:
        return ClaudeReceipt(False, None, None, None, None, None, None, None, None, None, None, None, None, {"error": "no_api_key"})
    raw = image_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode()
    ext = image_path.suffix.lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    msg = await client.messages.create(
        model=settings.ocr_model,
        max_tokens=900,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    return _coerce(_parse_response(text))


async def extract_path(path: Path) -> ClaudeReceipt:
    if path.suffix.lower() == ".pdf":
        return await extract_from_pdf(path)
    return await extract_from_image(path)
