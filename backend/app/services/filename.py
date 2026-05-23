"""Build receipt filenames from a template + extracted metadata.

Default template: `{date}_{provider}_{client}_{amount}-{currency}`
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal


def _slugify(text: str | None, default: str = "Unknown") -> str:
    if not text:
        return default
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-")
    return s or default


def format_amount(amount: Decimal | float | str | None) -> str:
    if amount is None:
        return "0.00"
    try:
        d = Decimal(str(amount))
    except Exception:
        return "0.00"
    return f"{d.quantize(Decimal('0.01'))}"


def build_filename(
    *, template: str, date: datetime | None, provider: str | None,
    client: str | None, amount: Decimal | float | str | None, currency: str | None,
    invoice_number: str | None = None,
) -> str:
    date_part = (date or datetime.utcnow()).strftime("%Y-%m-%d")
    parts = {
        "date": date_part,
        "provider": _slugify(provider, "Provider"),
        "client": _slugify(client, "General"),
        "amount": format_amount(amount),
        "currency": (currency or "CHF").upper(),
        "invoice_number": _slugify(invoice_number) if invoice_number else "",
    }
    name = template.format_map(_DefaultDict(parts))
    # Strip duplicate separators that arise when client/invoice_number are blank
    name = re.sub(r"_+", "_", name).strip("_")
    return name + ".pdf"


class _DefaultDict(dict):
    def __missing__(self, key: str) -> str:
        return ""
