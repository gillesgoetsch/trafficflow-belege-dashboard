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


_PROMPT = """You are extracting structured metadata from a financial document for an SMB
bookkeeping system. The document can be one of several types — classify it first.

Return STRICT JSON in this exact shape:

{
  "document_type": "receipt" | "document" | "upcoming" | "other",
  "is_receipt": true | false,                    // shortcut: true iff document_type=="receipt"
  "vendor": "Vendor / company that issued it" | null,
  "vendor_slug": "lowercase-kebab-slug" | null,
  "customer_hint": "If the BILLED TO / Rechnung an / customer line names an org/brand/person, return it verbatim. Otherwise null.",
  "document_date": "YYYY-MM-DD" | null,           // ISSUE DATE — see rules below
  "due_date": "YYYY-MM-DD" | null,                // PAYMENT DUE — see rules below
  "total_amount": "1234.56" | null,               // gross / Brutto / total-incl-VAT, dot decimal
  "currency": "CHF" | "EUR" | "USD" | "GBP" | "...",
  "vat_rate": "8.1" | "2.6" | "0" | null,
  "vat_amount": "12.34" | null,
  "invoice_number": "INV-..." | null,
  "language": "de" | "en" | "fr" | "it" | null,
  "notes": "one-line plain summary"
}

------------------------------------------------------------------
DOCUMENT TYPE — pick exactly ONE. DEFAULT to "receipt" — the vast majority
of uploads ARE receipts. Only deviate when the markers below are obvious.
------------------------------------------------------------------
- "receipt"  : a paid OR payable invoice / Rechnung / Quittung / Beleg / Receipt.
               Has a vendor, an amount, and an issue date. THIS IS THE DEFAULT.
               Anything that looks like a normal bill, even from SaaS tools
               (Notion, Adobe, ChatGPT, Claude, Digitec, Amazon, Netcup, Bexio,
               etc.) is a "receipt". Bank-transfer receipts and credit-card
               charges with proof are receipts. Twint screenshots with a
               clearly stamped amount are receipts.

- "upcoming" : Classify as "upcoming" ONLY if you see one of these explicit
               markers on the document itself:
                 * "Upcoming - not due yet" / "Status: Upcoming"
                 * "Vorabrechnung" / "Preview invoice" / "Draft invoice"
                 * "Will be charged on …" / "Scheduled for …"
               Notion in particular sends "Upcoming" invoices for next month's
               charge — those ARE upcoming. Without an explicit marker like
               above, keep "receipt".

- "document" : ONLY if it is clearly NOT an invoice — a packing slip
               (Lieferschein), delivery confirmation, attestation, contract,
               certificate, terms of service. No amount visible and no
               "Rechnung/Invoice/Receipt" wording. Random scan of a non-bill.

- "other"    : Marketing email PDFs, gibberish, blank pages, screenshots of
               unrelated things. If you can read an amount + a vendor, it is
               NOT "other".

------------------------------------------------------------------
DATE RULES — most common mistake area, read carefully
------------------------------------------------------------------
document_date = DATE OF ISSUE (Rechnungsdatum / Invoice Date / Issue Date /
"Erstellt am" / "Datum"). It's what gets printed at the TOP of the invoice
as the document's own date. This drives the accounting period.

due_date = DATE PAYMENT IS DUE (Fälligkeitsdatum / Fällig am / Due Date /
Payment Due / Zahlbar bis). On the document this is usually a SEPARATE labeled
field, often a few days or a month after the issue date.

CRITICAL date rules:
1. NEVER copy document_date into due_date. If only ONE date is visible and it
   isn't explicitly labeled "Due", put it in document_date and leave due_date
   null.
2. Many receipts have NO due date because they were already paid (credit-card
   charges, instant Twint, Stripe receipts). In that case → due_date = null.
3. Labels matter more than position. "Bill Date" usually = issue date.
   "Service Period" / "Subscription Period" date ranges are NOT the issue date.
4. For Twint / PostFinance / e-payment screenshots: look for "Datum",
   "ausgeführt am", or a date stamped on the receipt. If you can't read it
   confidently, return null — DO NOT use today's date.
5. For bank-transfer scans where you can read a date stamp from the bank or
   merchant on the document, use that. If only the filename has a date and
   the image itself has none, return null.

------------------------------------------------------------------
AMOUNT RULES
------------------------------------------------------------------
- total_amount = GROSS / Brutto / total-including-VAT.
- If both Netto and Brutto are shown, return Brutto.
- Ignore numbers inside product names: "Porsche 911", "Boeing 747", "iPhone 13".
- Decimal point in OUTPUT: convert "119,10" → "119.10".
- Do NOT include currency symbol in the amount string.

------------------------------------------------------------------
Return ONLY the JSON object — no preamble, no markdown fences."""


@dataclass
class ClaudeReceipt:
    is_receipt: bool
    document_type: str           # receipt | document | upcoming | other
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
    dt = (data.get("document_type") or "").lower()
    if dt not in ("receipt", "document", "upcoming", "other"):
        # Fall back from legacy is_receipt boolean
        dt = "receipt" if data.get("is_receipt") else "other"
    return ClaudeReceipt(
        is_receipt=(dt == "receipt"),
        document_type=dt,
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
        # Signal "extraction unavailable" — caller should NOT overwrite existing
        # receipt data with junk.
        return ClaudeReceipt(False, "__unavailable__", None, None, None, None, None, None, None, None, None, None, None, None, {"error": "render_failed"})

    if not png_bytes:
        return ClaudeReceipt(False, "__unavailable__", None, None, None, None, None, None, None, None, None, None, None, None, {"error": "no_png"})

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
        return ClaudeReceipt(False, "__unavailable__", None, None, None, None, None, None, None, None, None, None, None, None, {"error": "no_api_key"})
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
        msg = str(e)
        logger.warning("claude_extract.pdf_failed_falling_back_to_vision", path=str(pdf_path), error=msg)
        # Hard fail (credits exhausted, auth, server outage) — signal unavailable
        # so the worker keeps existing receipt data instead of wiping it.
        if any(k in msg.lower() for k in ("credit balance", "billing", "401", "403", "overloaded")):
            return ClaudeReceipt(False, "__unavailable__", None, None, None, None, None, None, None, None, None, None, None, None, {"error": "api_unavailable", "detail": msg[:200]})

    # Render to image and try Vision (handles image-only scanned PDFs)
    return await _vision_fallback_pdf(pdf_path, client)


async def extract_from_image(image_path: Path) -> ClaudeReceipt:
    if not settings.anthropic_api_key:
        return ClaudeReceipt(False, "__unavailable__", None, None, None, None, None, None, None, None, None, None, None, None, {"error": "no_api_key"})
    raw = image_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode()
    ext = image_path.suffix.lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
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
    except Exception as e:  # noqa: BLE001
        logger.warning("claude_extract.image_failed", path=str(image_path), error=str(e))
        return ClaudeReceipt(False, "__unavailable__", None, None, None, None, None, None, None, None, None, None, None, None, {"error": "api_unavailable", "detail": str(e)[:200]})
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    return _coerce(_parse_response(text))


async def extract_path(path: Path) -> ClaudeReceipt:
    if path.suffix.lower() == ".pdf":
        return await extract_from_pdf(path)
    return await extract_from_image(path)
