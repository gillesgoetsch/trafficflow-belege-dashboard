"""accountant fields: notes, VAT, booking status

Revision ID: 0003_accountant
Revises: 0002_payment_brand
Create Date: 2026-05-25 00:00:00

Adds fields needed for monthly closing / bookkeeping:
- notes               free text, why is this expense (e.g. "office rent for Q1")
- vat_rate            VAT %, defaults 0; CH rates: 8.1, 2.6, 3.8, 0.0
- vat_amount          explicit VAT amount in receipt currency (overrides computed)
- booked_at           when accountant marked it as exported to bookkeeping
- bookkeeping_ref     external reference (e.g. Bexio document ID, journal entry #)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_accountant"
down_revision: Union[str, None] = "0002_payment_brand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("receipts", sa.Column("notes", sa.Text, nullable=True))
    op.add_column("receipts", sa.Column("vat_rate", sa.Numeric(5, 2), nullable=True))
    op.add_column("receipts", sa.Column("vat_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("receipts", sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("receipts", sa.Column("bookkeeping_ref", sa.String(128), nullable=True))
    op.create_index("ix_receipts_booked_at", "receipts", ["booked_at"])


def downgrade() -> None:
    op.drop_index("ix_receipts_booked_at", table_name="receipts")
    for col in ("bookkeeping_ref", "booked_at", "vat_amount", "vat_rate", "notes"):
        op.drop_column("receipts", col)
