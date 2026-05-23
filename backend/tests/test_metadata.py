"""Quick regex-based metadata extraction smoke tests."""
from app.services.metadata_extract import extract


def test_extract_swiss_invoice_text():
    text = """Rechnung Nr. R-2026-001
Datum: 15.01.2026
Total CHF 1'234.56"""
    meta = extract(text)
    assert meta.amount is not None
    assert float(meta.amount) == 1234.56
    assert meta.currency == "CHF"
    assert meta.invoice_number == "R-2026-001"


def test_extract_english_invoice():
    text = "Invoice #INV-9001\nDate: 2026-02-15\nGrand Total: $42.00"
    meta = extract(text)
    assert meta.amount is not None
    assert float(meta.amount) == 42.0
    assert meta.currency == "USD"
    assert meta.invoice_number == "INV-9001"
