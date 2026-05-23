"""Claude Sonnet Vision OCR + structured metadata extraction.

Given a PDF or image (scanned/photographed receipt), in a single API call we
get back text + {date, amount, currency, provider, invoice_number, language}.

For multi-page PDFs we render pages to images first (Playwright/PIL approach
would be heavy here, so we use the `pdf2image` substitute via `pdfminer` for
text and only fall back to Vision if text extraction fails).
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from anthropic import AsyncAnthropic
from PIL import Image
from pypdf import PdfReader

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


_OCR_PROMPT = """You receive an image of a receipt/invoice. Extract structured metadata and a clean text transcription.

Return STRICT JSON ONLY in this exact shape:
{
  "is_receipt": true|false,
  "date": "YYYY-MM-DD" | null,
  "amount": "1234.56" | null,           // string, as on the document
  "currency": "CHF" | "EUR" | "USD" | "GBP" | null,
  "provider": "Vendor name as printed" | null,
  "provider_slug": "vendor-kebab-slug" | null,
  "invoice_number": "..." | null,
  "language": "de" | "en" | "fr" | "it" | null,
  "text": "the full extracted text, line-broken"
}

If the document is clearly not a receipt or invoice, set is_receipt=false and leave fields null."""


@dataclass
class OcrResult:
    is_receipt: bool
    date: str | None
    amount: str | None
    currency: str | None
    provider: str | None
    provider_slug: str | None
    invoice_number: str | None
    language: str | None
    text: str
    raw: dict


async def ocr_image_bytes(image_bytes: bytes, media_type: str = "image/jpeg") -> OcrResult:
    """Run Claude Sonnet Vision against an image."""
    if not settings.anthropic_api_key:
        return OcrResult(False, None, None, None, None, None, None, None, "", {"error": "no_api_key"})
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    b64 = base64.b64encode(image_bytes).decode()
    msg = await client.messages.create(
        model=settings.ocr_model,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": _OCR_PROMPT},
                ],
            }
        ],
    )
    text = ""
    for block in msg.content:
        if getattr(block, "type", "") == "text":
            text += block.text
    return _parse_ocr_json(text)


def _parse_ocr_json(text: str) -> OcrResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return OcrResult(False, None, None, None, None, None, None, None, text, {"error": "no_json"})
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return OcrResult(False, None, None, None, None, None, None, None, text, {"error": "bad_json"})
    return OcrResult(
        is_receipt=bool(data.get("is_receipt")),
        date=data.get("date"),
        amount=data.get("amount"),
        currency=data.get("currency"),
        provider=data.get("provider"),
        provider_slug=data.get("provider_slug"),
        invoice_number=data.get("invoice_number"),
        language=data.get("language"),
        text=data.get("text") or "",
        raw=data,
    )


def native_text(pdf_path: Path) -> str:
    """Try pure-text extraction from a (digital, non-scanned) PDF."""
    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:  # noqa: BLE001
        logger.debug("ocr.native_text.failed", error=str(e))
        return ""


def is_likely_scanned(pdf_path: Path, *, min_chars_per_page: int = 80) -> bool:
    """A PDF with very little extractable text is probably scanned."""
    try:
        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            return True
        total = sum(len((p.extract_text() or "").strip()) for p in reader.pages)
        return total < (min_chars_per_page * len(reader.pages))
    except Exception:
        return True


async def ocr_pdf(pdf_path: Path) -> OcrResult:
    """Run OCR on a PDF — uses Sonnet Vision on the first page rendered as image."""
    # We render the first page using Playwright/pillow? Simpler:
    # convert via Pillow + PyPDF page->image (use Playwright by loading the PDF in chrome).
    # The reliable, dependency-light path: render the first page to PNG via Playwright.
    from playwright.async_api import async_playwright

    pdf_url = pdf_path.absolute().as_uri()
    png_bytes: bytes = b""
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            context = await browser.new_context(viewport={"width": 1240, "height": 1754})
            page = await context.new_page()
            await page.goto(pdf_url, wait_until="load", timeout=20000)
            await page.wait_for_timeout(1500)
            png_bytes = await page.screenshot(full_page=True, type="png")
        finally:
            await browser.close()
    if not png_bytes:
        return OcrResult(False, None, None, None, None, None, None, None, "", {"error": "render_failed"})
    return await ocr_image_bytes(png_bytes, media_type="image/png")


async def ocr_image_file(image_path: Path) -> OcrResult:
    ext = image_path.suffix.lower()
    media = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(ext, "image/jpeg")
    return await ocr_image_bytes(image_path.read_bytes(), media_type=media)
