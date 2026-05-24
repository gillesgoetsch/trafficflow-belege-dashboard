"""Bexio sync: connector mode + auto_book, sync_target payload logging, provider account mappings

Revision ID: 0007_bexio_sync
Revises: 0006_document_type
Create Date: 2026-05-29 00:00:00

Three-state per-connector sync:
- off       — silent, nothing happens
- dry_run   — build payload, log it, never POST
- live      — POST for real, capture response

Adds request/response logging on sync_targets so every outbound call is auditable.
Adds (provider × organization) → (account_code, vat_code) so the Bexio kb_bill
auto-fill knows which chart-of-accounts entry to book against.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_bexio_sync"
down_revision: Union[str, None] = "0006_document_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # connector_mode enum (new)
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE connector_mode AS ENUM ('off', 'dry_run', 'live'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    )

    # connectors.mode + auto_book
    op.add_column(
        "connectors",
        sa.Column(
            "mode",
            postgresql.ENUM(name="connector_mode", create_type=False),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column(
        "connectors",
        sa.Column("auto_book", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # sync_status.dry_run_ok — add to existing enum
    # Postgres 12+ allows ALTER TYPE ADD VALUE inside a transaction; IF NOT EXISTS for re-runs.
    op.execute("ALTER TYPE sync_status ADD VALUE IF NOT EXISTS 'dry_run_ok'")

    # sync_targets payload logging columns
    op.add_column(
        "sync_targets",
        sa.Column(
            "mode",
            postgresql.ENUM(name="connector_mode", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "sync_targets",
        sa.Column("request_payload", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "sync_targets",
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "sync_targets",
        sa.Column("response_status_code", sa.Integer(), nullable=True),
    )

    # provider_account_mappings — per (org, provider) bookkeeping settings
    op.create_table(
        "provider_account_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account_code", sa.String(32), nullable=False),
        sa.Column("vat_code", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "provider_id", "organization_id", name="uq_provider_account_mapping",
        ),
    )
    op.create_index(
        "ix_provider_account_mappings_org",
        "provider_account_mappings",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_account_mappings_org",
        table_name="provider_account_mappings",
    )
    op.drop_table("provider_account_mappings")
    op.drop_column("sync_targets", "response_status_code")
    op.drop_column("sync_targets", "response_payload")
    op.drop_column("sync_targets", "request_payload")
    op.drop_column("sync_targets", "mode")
    op.drop_column("connectors", "auto_book")
    op.drop_column("connectors", "mode")
    # NB: removing a value from a Postgres enum is not supported — sync_status keeps dry_run_ok.
    op.execute("DROP TYPE IF EXISTS connector_mode")
