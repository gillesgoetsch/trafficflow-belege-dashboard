"""Best-effort metadata extraction (date, amount, currency, invoice_no) from text.

Falls back to LLM in `ocr.py` but most receipts can be parsed with regex.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from dateutil import parser as dateparser


CURRENCY_HINTS = {
    "CHF": (r"\bCHF\b", r"\bFr\.?\b", r"\bSFr\.?\b"),
    "EUR": (r"\bEUR\b", r"€"),
    "USD": (r"\bUSD\b", r"\$"),
    "GBP": (r"\bGBP\b", r"£"),
}


@dataclass
class ExtractedMeta:
    date: datetime | None
    amount: Decimal | None
    currency: str | None
    invoice_number: str | None
    language: str | None


_DATE_PATTERNS = [
    r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b",
    r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b",
    r"\b(\d{1,2})\.\s*(?:Jan|Feb|M[aä]rz|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)[a-zäöü]*\.?\s*(\d{4})\b",
]


def parse_first_date(text: str) -> datetime | None:
    for pat in _DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if not m:
            continue
        try:
            return dateparser.parse(m.group(0), dayfirst=True, fuzzy=True)
        except (ValueError, dateparser.ParserError):  # type: ignore[attr-defined]
            continue
    # Last resort: dateutil fuzzy
    try:
        return dateparser.parse(text[:1000], fuzzy=True, dayfirst=True)
    except Exception:
        return None


_AMOUNT_LINE = re.compile(
    r"(?P<label>total|gesamt|summe|total amount|amount due|zu zahlen|rechnungsbetrag|grand total)"
    r"[^\d]{0,30}(?P<cur>CHF|EUR|USD|GBP|Fr\.?|€|\$|£)?\s*(?P<amt>\d{1,3}(?:[ '.,]\d{3})*(?:[.,]\d{2})?)",
    re.IGNORECASE,
)
_AMOUNT_FALLBACK = re.compile(
    r"(?P<cur>CHF|EUR|USD|GBP|Fr\.?|€|\$|£)\s*(?P<amt>\d{1,3}(?:[ '.,]\d{3})*(?:[.,]\d{2}))"
)


def _normalize_amount(raw: str) -> Decimal | None:
    s = raw.strip().replace(" ", "").replace("'", "")
    # If both '.' and ',' present, assume the rightmost is the decimal sep.
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Heuristic: assume comma is decimal sep if exactly two digits follow.
        if re.search(r",\d{2}\b", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return Decimal(s)
    except Exception:
        return None


def parse_amount(text: str) -> tuple[Decimal | None, str | None]:
    """Return (amount, currency) — best-effort."""
    if not text:
        return None, None
    sym_to_iso = {"€": "EUR", "$": "USD", "£": "GBP", "Fr.": "CHF", "Fr": "CHF"}

    for m in _AMOUNT_LINE.finditer(text):
        amt = _normalize_amount(m.group("amt"))
        cur = m.group("cur")
        iso = sym_to_iso.get(cur or "", cur)
        return amt, iso
    m = _AMOUNT_FALLBACK.search(text)
    if m:
        amt = _normalize_amount(m.group("amt"))
        cur = m.group("cur")
        iso = sym_to_iso.get(cur or "", cur)
        return amt, iso
    # Maybe just one currency mentioned but no amount near it
    for iso, pats in CURRENCY_HINTS.items():
        if any(re.search(p, text) for p in pats):
            return None, iso
    return None, None


_INV_RE = re.compile(
    r"\b(?:Rechnung[s\-]?(?:Nr\.?|Nummer)|Invoice(?:\s*No\.?|\s*Number|\s*#)|Beleg(?:\-)?Nr\.?|Order(?:\s*ID|\s*#)?)\s*"
    r"[:#]?\s*([A-Z0-9\-_/]{4,30})", re.IGNORECASE,
)


def parse_invoice_number(text: str) -> str | None:
    if not text:
        return None
    m = _INV_RE.search(text)
    return m.group(1) if m else None


def guess_language(text: str) -> str | None:
    if not text:
        return None
    lo = text.lower()
    hits = {
        "de": sum(lo.count(w) for w in (" rechnung", " betrag", " ihre ", " mwst", " kunde", " danke")),
        "en": sum(lo.count(w) for w in (" invoice", " amount", " your ", " thanks", " customer", " total")),
        "fr": sum(lo.count(w) for w in (" facture", " montant", " votre ", " client", " merci")),
        "it": sum(lo.count(w) for w in (" fattura", " importo", " cliente", " grazie")),
    }
    if not any(hits.values()):
        return None
    return max(hits, key=hits.get)


def extract(text: str) -> ExtractedMeta:
    if not text:
        return ExtractedMeta(None, None, None, None, None)
    amt, cur = parse_amount(text)
    return ExtractedMeta(
        date=parse_first_date(text),
        amount=amt,
        currency=cur,
        invoice_number=parse_invoice_number(text),
        language=guess_language(text),
    )
