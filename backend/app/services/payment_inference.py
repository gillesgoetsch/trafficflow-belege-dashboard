"""Local payment-method inference from PDF text.

No API calls — uses pypdf to read native text and scans for credit-card
brand names, Twint, PostFinance markers, etc. Used as a fallback to
fix payment_method on receipts where the user uploaded with the default
"unknown" / "bank_transfer" but the document clearly shows e.g. VISA.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.db.models import PaymentMethod


_CREDIT_CARD_PATTERNS = re.compile(
    r"\b("
    r"visa"
    r"|mastercard|master\s*card|maestro"
    r"|american\s*express|amex"
    r"|kreditkarte|credit[-\s]?card"
    r"|card\s*ending|card\s*number"
    r"|charged\s+to\s+(your\s+)?card"
    r"|\*{4,}\s*\d{4}"  # masked card number "**** 1234"
    r")\b",
    re.IGNORECASE,
)
_TWINT_PATTERN = re.compile(r"\btwint\b", re.IGNORECASE)
_POSTFINANCE_PATTERN = re.compile(r"\bpostfinance\b", re.IGNORECASE)
_PAYPAL_PATTERN = re.compile(r"\bpaypal\b", re.IGNORECASE)
_CASH_PATTERN = re.compile(r"\b(bar(?:zahlung)?|cash|in\s+cash)\b", re.IGNORECASE)
_BANK_TRANSFER_PATTERN = re.compile(
    r"\b("
    r"banküberweisung|bank\s*transfer|wire\s*transfer"
    r"|iban\s*:?\s*[A-Z]{2}\d"
    r"|esr|qr-rechnung|qr\s*bill"
    r")\b",
    re.IGNORECASE,
)


def extract_pdf_text(path: Path, max_pages: int = 3, max_chars: int = 20000) -> str:
    """Best-effort native PDF text extraction. Returns empty string on failure."""
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
            if i >= max_pages:
                break
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(parts)[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


def infer_payment_method(text: str, filename: str = "") -> PaymentMethod | None:
    """Return a PaymentMethod when the document contains a strong marker.

    Returns None when nothing matches — caller should keep the existing value.
    Order matters: credit-card markers win over IBAN, because credit-card
    receipts often also include the merchant's bank info.
    """
    haystack = f"{text}\n{filename}"
    if not haystack.strip():
        return None
    if _CREDIT_CARD_PATTERNS.search(haystack):
        return PaymentMethod.credit_card
    if _TWINT_PATTERN.search(haystack):
        return PaymentMethod.twint
    if _PAYPAL_PATTERN.search(haystack):
        return PaymentMethod.paypal
    if _POSTFINANCE_PATTERN.search(haystack) and _BANK_TRANSFER_PATTERN.search(haystack):
        return PaymentMethod.bank_transfer
    if _CASH_PATTERN.search(haystack):
        return PaymentMethod.cash
    if _BANK_TRANSFER_PATTERN.search(haystack):
        return PaymentMethod.bank_transfer
    return None
