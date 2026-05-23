"""payment_method + brand on receipts, drop leckker/sichersatt sub-clients

Revision ID: 0002_payment_brand
Revises: 0001_init
Create Date: 2026-05-24 00:00:00

Reasoning:
- `payment_method` distinguishes credit-card vs bank-transfer vs Twint vs cash.
  Drives separate reporting flows and connector routing later.
- `brand` is a free-text tag (e.g. 'leckker', 'sichersatt') for sub-branding
  inside one organization. Lighter-weight than a sub-Client; doesn't need
  separate mailboxes/connectors of its own.
- Remove the seeded leckker/sichersatt `clients` rows — they are brands of
  one and the same legal client (SicherSatt AG, the org itself), not separate
  sub-tenants. Receipts get tagged via the new `brand` column instead.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_payment_brand"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # payment_method enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE payment_method AS ENUM "
        "('credit_card', 'bank_transfer', 'twint', 'cash', 'paypal', 'other', 'unknown'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    )

    payment_method_enum = sa.dialects.postgresql.ENUM(
        name="payment_method", create_type=False
    )
    op.add_column(
        "receipts",
        sa.Column(
            "payment_method", payment_method_enum,
            nullable=False, server_default="unknown",
        ),
    )
    op.create_index("ix_receipts_payment_method", "receipts", ["payment_method"])

    # Brand — short tag, indexed for fast filter
    op.add_column("receipts", sa.Column("brand", sa.String(64), nullable=True))
    op.create_index("ix_receipts_brand", "receipts", ["brand"])

    # Drop the seeded brand-as-clients rows. CASCADE on the FK takes their mappings.
    op.execute("DELETE FROM clients WHERE slug IN ('leckker', 'sichersatt')")


def downgrade() -> None:
    op.drop_index("ix_receipts_brand", table_name="receipts")
    op.drop_column("receipts", "brand")
    op.drop_index("ix_receipts_payment_method", table_name="receipts")
    op.drop_column("receipts", "payment_method")
    op.execute("DROP TYPE IF EXISTS payment_method")
