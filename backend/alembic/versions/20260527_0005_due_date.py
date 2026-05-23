"""Add due_date column to receipts; document_date is the date of issue.

Revision ID: 0005_due_date
Revises: 0004_routing_users
Create Date: 2026-05-27 00:00:00

`document_date` becomes the canonical "date of issue" (Rechnungsdatum). New
`due_date` (Fälligkeitsdatum) is when payment is owed. Most table views
should use `document_date` — the date of issue is the more important one
for accounting.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_due_date"
down_revision: Union[str, None] = "0004_routing_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("receipts", sa.Column("due_date", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_receipts_due_date", "receipts", ["due_date"])


def downgrade() -> None:
    op.drop_index("ix_receipts_due_date", table_name="receipts")
    op.drop_column("receipts", "due_date")
