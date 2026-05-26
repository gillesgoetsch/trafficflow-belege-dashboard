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


def _sane(dt: datetime | None) -> datetime | None:
    """Reject obvious garbage: too far in the future, before 2005."""
    if not dt:
        return None
    from datetime import datetime as _dt
    now = _dt.now()
    if dt.replace(tzinfo=None) > now.replace(tzinfo=None) + __import__("datetime").timedelta(days=60):
        return None
    if dt.year < 2005:
        return None
    return dt


def parse_first_date(text: str) -> datetime | None:
    for pat in _DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if not m:
            continue
        try:
            parsed = dateparser.parse(m.group(0), dayfirst=True, fuzzy=True)
            if (sane := _sane(parsed)):
                return sane
        except (ValueError, dateparser.ParserError):  # type: ignore[attr-defined]
            continue
    # Fuzzy last resort, but only if we get a sane date out
    try:
        return _sane(dateparser.parse(text[:1000], fuzzy=True, dayfirst=True))
    except Exception:
        return None


# Label-anchored amount: requires a word boundary on BOTH sides so "gesamt"
# does NOT match "Gesamtpreis" (column header). "rechnungsbetrag" /
# "gesamtbetrag" are the strongest signals (Netcup-style invoices).
_AMOUNT_LINE = re.compile(
    r"(?P<label>rechnungsbetrag|gesamtbetrag|grand\s*total|total\s*amount|amount\s*due"
    r"|zu\s*zahlen|gesamt|summe|total)\b"
    r"[^\d]{0,30}(?P<cur>CHF|EUR|USD|GBP|Fr\.?|€|\$|£)?\s*"
    r"(?P<amt>\d{1,3}(?:[ '.,]\d{3})*(?:[.,]\d{2})?)\s*"
    r"(?P<curaft>CHF|EUR|USD|GBP|Fr\.?|€|\$|£)?",
    re.IGNORECASE,
)
_AMOUNT_FALLBACK = re.compile(
    r"(?P<cur>CHF|EUR|USD|GBP|Fr\.?|€|\$|£)\s*(?P<amt>\d{1,3}(?:[ '.,]\d{3})*(?:[.,]\d{2}))"
)
_LABEL_PRIORITY = {
    "rechnungsbetrag": 100,
    "gesamtbetrag": 95,
    "grand total": 90,
    "total amount": 85,
    "amount due": 80,
    "zu zahlen": 75,
    "summe": 60,
    "total": 50,
    "gesamt": 40,
}


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
    """Return (amount, currency) — best-effort.

    Strategy: gather all label-anchored hits, pick the highest-priority
    label, and within that label the LAST occurrence (totals on multi-page
    invoices appear at the bottom). Falls back to currency-first scan.
    Currency may appear before OR after the amount ("8,24 EUR" vs "EUR 8,24").
    """
    if not text:
        return None, None
    sym_to_iso = {"€": "EUR", "$": "USD", "£": "GBP", "Fr.": "CHF", "Fr": "CHF"}

    hits: list[tuple[int, int, Decimal | None, str | None]] = []
    for m in _AMOUNT_LINE.finditer(text):
        label = re.sub(r"\s+", " ", m.group("label").lower()).strip()
        prio = _LABEL_PRIORITY.get(label, 30)
        amt = _normalize_amount(m.group("amt"))
        if amt is None:
            continue
        cur = m.group("cur") or m.group("curaft")
        iso = sym_to_iso.get(cur or "", cur)
        hits.append((prio, m.start(), amt, iso))

    if hits:
        # Highest priority wins; ties → last occurrence in the document.
        hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
        # If currency missing on the chosen hit, infer from the doc.
        amt, iso = hits[0][2], hits[0][3]
        if not iso:
            iso = _infer_currency(text)
        return amt, iso

    m = _AMOUNT_FALLBACK.search(text)
    if m:
        amt = _normalize_amount(m.group("amt"))
        cur = m.group("cur")
        iso = sym_to_iso.get(cur or "", cur)
        return amt, iso
    # Maybe just one currency mentioned but no amount near it
    iso = _infer_currency(text)
    return None, iso


def _infer_currency(text: str) -> str | None:
    """Pick the currency code/symbol that appears most often in the document."""
    counts: dict[str, int] = {}
    for iso, pats in CURRENCY_HINTS.items():
        c = sum(len(re.findall(p, text)) for p in pats)
        if c:
            counts[iso] = c
    if not counts:
        return None
    return max(counts, key=counts.get)


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
