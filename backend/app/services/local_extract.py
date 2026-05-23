"""Local LLM-based receipt metadata extraction.

Runs Qwen2.5-3B-Instruct (Q4_K_M GGUF, ~1.8 GB) via llama-cpp-python with
grammar-constrained JSON output. Same return shape as `claude_extract.py`
so callers can swap engines transparently.

Tradeoffs vs Claude:
- No external API call, no $-cost, no data leaving the VPS.
- ARM CPU inference: ~15-30 s per receipt.
- Accuracy is lower than Claude on complex layouts. Use the confidence
  gate in the pipeline to decide if the result is trustworthy.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dateutil import parser as dateparser

from app.core.logging import get_logger
from app.services.claude_extract import ClaudeReceipt  # reuse the dataclass

logger = get_logger(__name__)


_MODEL_PATH = Path(os.environ.get("LOCAL_LLM_MODEL_PATH", "/models/qwen2.5-3b-instruct-q4_k_m.gguf"))
_MODEL_LOCK = threading.Lock()
_MODEL_INSTANCE: Any = None  # llama_cpp.Llama


_JSON_GRAMMAR = r'''
root   ::= object
object ::= "{" ws kvs? ws "}"
kvs    ::= kv (ws "," ws kv)*
kv     ::= string ws ":" ws value
value  ::= string | number | object | array | "true" | "false" | "null"
array  ::= "[" ws (value (ws "," ws value)*)? ws "]"
string ::= "\"" chars "\""
chars  ::= char*
char   ::= [^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]
number ::= "-"? ("0" | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
ws     ::= [ \t\n]*
'''


_PROMPT_HEAD = """You are extracting structured metadata from a financial document for a Swiss SMB
bookkeeping system. Output ONLY a single JSON object — no preamble, no markdown
fences, no commentary.

JSON shape (every field required, use null when unknown):

{
  "document_type": "receipt" | "document" | "upcoming" | "other",
  "is_receipt": true | false,
  "vendor": string | null,
  "vendor_slug": string | null,
  "customer_hint": string | null,
  "document_date": "YYYY-MM-DD" | null,
  "due_date": "YYYY-MM-DD" | null,
  "total_amount": "1234.56" | null,
  "currency": "CHF" | "EUR" | "USD" | "GBP" | string | null,
  "vat_rate": "8.1" | "2.6" | "0" | null,
  "vat_amount": "12.34" | null,
  "invoice_number": string | null,
  "language": "de" | "en" | "fr" | "it" | null,
  "notes": string | null
}

DOCUMENT TYPE RULES — pick exactly ONE. DEFAULT is "receipt".

- "receipt" : default. A bill / invoice / Rechnung / Quittung / Beleg / Receipt
  with a vendor, amount, and date. Includes SaaS subscriptions (Notion, Adobe,
  ChatGPT, Slack, Bexio), e-commerce (Digitec, Amazon), hosting (Netcup),
  Twint screenshots with a stamped amount, credit-card receipts.
- "upcoming" : ONLY if the document explicitly says one of:
  "Upcoming - not due yet", "Status: Upcoming", "Vorabrechnung",
  "Preview invoice", "Draft invoice", "Will be charged on", "Scheduled for".
- "document" : a clearly non-invoice file (Lieferschein / packing slip,
  delivery confirmation, contract, certificate, attestation, ToS) with NO
  amount and NO "Rechnung/Invoice/Receipt" wording.
- "other" : marketing PDFs, gibberish, blank pages. If you can read an amount
  AND a vendor it is NOT "other".

DATE RULES — most-common mistake area:

document_date = DATE OF ISSUE (Rechnungsdatum / Invoice Date / Issue Date /
"Erstellt am" / "Datum"). Printed at the top of the invoice. Drives accounting.

due_date = PAYMENT DUE (Fälligkeitsdatum / Fällig am / Due Date / Payment Due /
Zahlbar bis). Usually a separate labeled field, days or a month after issue.

CRITICAL:
1. NEVER copy document_date into due_date. If only ONE date is visible and it
   isn't explicitly labeled "Due/Fällig", put it in document_date and leave
   due_date null.
2. Credit-card / Twint / Stripe receipts usually have NO due_date — they were
   paid at the moment. due_date = null.
3. For Twint / PostFinance / e-payment screenshots: look for "Datum",
   "ausgeführt am", or a stamped date. If you can't read it confidently,
   return null — DO NOT use today's date.

AMOUNT RULES:

- total_amount = GROSS / Brutto / total-including-VAT.
- If both Netto and Brutto are shown, return Brutto.
- Ignore numbers in product names: "Porsche 911", "iPhone 13".
- Convert "119,10" to "119.10". No currency symbol in the amount string.

------------------------------------------------------------------
DOCUMENT TEXT:
"""


def _get_model():
    """Lazy singleton — load the model on first use and reuse across jobs."""
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is not None:
        return _MODEL_INSTANCE
    with _MODEL_LOCK:
        if _MODEL_INSTANCE is not None:
            return _MODEL_INSTANCE
        if not _MODEL_PATH.exists():
            logger.warning("local_extract.model_missing", path=str(_MODEL_PATH))
            return None
        try:
            from llama_cpp import Llama
        except ImportError:
            logger.error("local_extract.llama_cpp_not_installed")
            return None
        logger.info("local_extract.loading_model", path=str(_MODEL_PATH))
        _MODEL_INSTANCE = Llama(
            model_path=str(_MODEL_PATH),
            n_ctx=8192,
            n_threads=int(os.environ.get("LOCAL_LLM_THREADS", "4")),
            n_gpu_layers=0,
            verbose=False,
        )
        logger.info("local_extract.model_loaded")
        return _MODEL_INSTANCE


def _to_decimal(v: Any) -> Decimal | None:
    if v in (None, "", "null"):
        return None
    try:
        s = str(v).replace(" ", "").replace("'", "")
        if "," in s and "." in s:
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
    except Exception:  # noqa: BLE001
        return None


def _coerce(data: dict) -> ClaudeReceipt:
    dt = (data.get("document_type") or "").lower()
    if dt not in ("receipt", "document", "upcoming", "other"):
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
    """Extract the JSON object from the model's reply. Grammar-constrained
    output is already strict JSON but we still tolerate stray whitespace.
    """
    if not text:
        return {}
    text = text.strip()
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


def _read_pdf_text(path: Path, max_chars: int = 14000) -> str:
    """Extract native PDF text via pypdf. Empty string on image-only PDFs."""
    if path.suffix.lower() != ".pdf":
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for i, page in enumerate(reader.pages):
            if i >= 4:
                break
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        text = "\n".join(parts)
        # Collapse runs of whitespace to reduce token bloat
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars]
    except Exception as e:  # noqa: BLE001
        logger.warning("local_extract.pdf_read_failed", path=str(path), error=str(e))
        return ""


def _unavailable(reason: str) -> ClaudeReceipt:
    return ClaudeReceipt(
        False, "__unavailable__", None, None, None, None, None, None, None,
        None, None, None, None, None, {"error": reason},
    )


async def extract_from_pdf(pdf_path: Path) -> ClaudeReceipt:
    text = _read_pdf_text(pdf_path)
    if not text or len(text.strip()) < 20:
        # Image-only PDF — local text model can't help.
        logger.info("local_extract.image_only_pdf", path=str(pdf_path))
        return _unavailable("image_only_pdf")
    return await _extract_from_text(text, source=str(pdf_path))


async def extract_from_image(image_path: Path) -> ClaudeReceipt:
    # We don't ship a local vision model — images go to Claude.
    return _unavailable("image_input_unsupported_locally")


async def extract_path(path: Path) -> ClaudeReceipt:
    if path.suffix.lower() == ".pdf":
        return await extract_from_pdf(path)
    return await extract_from_image(path)


async def _extract_from_text(text: str, source: str = "") -> ClaudeReceipt:
    model = _get_model()
    if model is None:
        return _unavailable("model_not_loaded")

    prompt = _PROMPT_HEAD + text + "\n\nReturn the JSON object only:\n"
    try:
        result = model.create_completion(
            prompt=prompt,
            max_tokens=600,
            temperature=0.0,
            top_p=0.95,
            grammar=None,  # JSON grammar prepared but llama-cpp-python takes a Grammar obj; we parse leniently
            stop=["```", "\n\n\n"],
        )
        text_out = result["choices"][0]["text"] if "choices" in result else ""
    except Exception as e:  # noqa: BLE001
        logger.warning("local_extract.inference_failed", source=source, error=str(e))
        return _unavailable(f"inference_failed: {str(e)[:120]}")

    data = _parse_response(text_out)
    if not data:
        logger.warning("local_extract.parse_failed", source=source, raw=text_out[:300])
        return _unavailable("parse_failed")
    return _coerce(data)


def is_confident(r: ClaudeReceipt, pdf_text: str | None = None) -> tuple[bool, str]:
    """Decide whether the local result is trustworthy enough to skip Claude.

    Returns (ok, reason). ok=True means use the local result; ok=False means
    fall back to the API for this receipt.

    Rules — all must pass for receipts:
    - document_type must be one of the four valid values
    - if document_type=='receipt': must have vendor AND amount AND document_date
    - amount must be positive, < 1e8
    - document_date must parse and be between 2010-01-01 and "today + 2 years"
    - if pdf_text contains multiple distinct money values (>= 3), require
      that the extracted amount matches one of the largest two (avoids the
      "9xx-Rechnung 911 vs 119.10" trap)
    """
    from datetime import date, timedelta

    if r.document_type not in ("receipt", "document", "upcoming", "other"):
        return False, "invalid_document_type"

    if r.document_type == "other":
        # "other" is a confident negative — accept without further checks.
        return True, "ok_other"

    if r.document_type == "document":
        # Documents may legitimately have no amount; still require a vendor or date.
        if not (r.vendor or r.document_date):
            return False, "document_missing_context"
        return True, "ok_document"

    # receipt / upcoming require the financial trio
    if not r.vendor:
        return False, "missing_vendor"
    if r.total_amount is None:
        return False, "missing_amount"
    try:
        amt = float(r.total_amount)
        if amt <= 0 or amt > 1e8:
            return False, f"implausible_amount:{amt}"
    except Exception:  # noqa: BLE001
        return False, "amount_not_numeric"

    if not r.document_date:
        return False, "missing_document_date"
    try:
        d = dateparser.parse(r.document_date).date()
        today = date.today()
        if d < date(2010, 1, 1):
            return False, f"date_too_old:{d}"
        if d > today + timedelta(days=2 * 365):
            return False, f"date_too_far_future:{d}"
    except Exception:  # noqa: BLE001
        return False, "date_unparseable"

    # Multi-amount disambiguation guard
    if pdf_text:
        amounts = re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))(?!\d)", pdf_text)
        nums: list[float] = []
        for a in amounts:
            try:
                normalized = a.replace(".", "").replace(",", ".") if a.rfind(",") > a.rfind(".") else a.replace(",", "")
                nums.append(float(normalized))
            except ValueError:
                continue
        # keep plausible-looking values only
        nums = [n for n in nums if 1 <= n < 1e7]
        if len(set(nums)) >= 3:
            top_two = sorted(set(nums), reverse=True)[:2]
            try:
                if not any(abs(float(r.total_amount) - t) < 0.02 for t in top_two):
                    return False, f"amount_not_in_top_two:{r.total_amount}_vs_{top_two}"
            except Exception:  # noqa: BLE001
                pass

    return True, "ok_receipt"
