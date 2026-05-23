"""Filename normalizer tests."""
from datetime import datetime
from decimal import Decimal

from app.services.filename import build_filename, format_amount


def test_basic_template():
    name = build_filename(
        template="{date}_{provider}_{client}_{amount}-{currency}",
        date=datetime(2026, 1, 15),
        provider="Facebook Ads",
        client="Leckker",
        amount=Decimal("7.53"),
        currency="chf",
    )
    assert name == "2026-01-15_Facebook-Ads_Leckker_7.53-CHF.pdf"


def test_missing_client_collapses_separators():
    name = build_filename(
        template="{date}_{provider}_{client}_{amount}-{currency}",
        date=datetime(2026, 3, 1),
        provider="Slack",
        client=None,
        amount="42",
        currency="USD",
    )
    assert "General" in name


def test_amount_formatting():
    assert format_amount(None) == "0.00"
    assert format_amount("12.5") == "12.50"
    assert format_amount(Decimal("12.345")) == "12.35"
