"""document_type column on receipts

Revision ID: 0006_document_type
Revises: 0005_due_date
Create Date: 2026-05-28 00:00:00

`receipt` table now holds different kinds of files:
- receipt   — paid / payable invoice (default)
- document  — legitimate non-invoice document (packing slip, attestation,
              membership confirmation, contract). Belongs in archive but not
              accounting flow.
- upcoming  — invoice marked "Upcoming / not due yet" by the vendor
              (Notion sends these in advance). Belongs in next-month books.
- other     — junk / not classifiable; usually filtered out.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_document_type"
down_revision: Union[str, None] = "0005_due_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE document_type AS ENUM ('receipt', 'document', 'upcoming', 'other'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    )
    op.add_column(
        "receipts",
        sa.Column(
            "document_type",
            sa.dialects.postgresql.ENUM(name="document_type", create_type=False),
            nullable=False, server_default="receipt",
        ),
    )
    op.create_index("ix_receipts_document_type", "receipts", ["document_type"])


def downgrade() -> None:
    op.drop_index("ix_receipts_document_type", table_name="receipts")
    op.drop_column("receipts", "document_type")
    op.execute("DROP TYPE IF EXISTS document_type")
