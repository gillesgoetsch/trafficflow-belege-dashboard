"""Inbound cloud folders for receipt + archive ingestion

Revision ID: 0009_inbound_folders
Revises: 0008_brand_routes_skip_rules
Create Date: 2026-05-31 00:00:00

Adds inbound-direction folder watching for Nextcloud / OneDrive /
Google Drive shared links + a local-mount option. The app polls each
folder, downloads new files, runs them through the existing pipeline
with a 'document_type=document' fallback when no receipt indicators
are extractable.

Two tables:
- inbound_folders: one row per (org, cloud folder) source
- inbound_files: per-file dedup + ingestion state
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_inbound_folders"
down_revision: Union[str, None] = "0008_brand_routes_skip_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE inbound_folder_type AS ENUM ("
        "'nextcloud_share', 'onedrive_share', 'gdrive_share', 'local_mount'"
        ")"
    )
    op.execute(
        "CREATE TYPE inbound_file_status AS ENUM ("
        "'pending', 'processing', 'processed', 'failed', 'not_a_receipt'"
        ")"
    )

    op.create_table(
        "inbound_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "type",
            sa.Enum(
                "nextcloud_share", "onedrive_share", "gdrive_share", "local_mount",
                name="inbound_folder_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("share_url", sa.String(1024), nullable=False),
        sa.Column("config_enc", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("batch_interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1000), nullable=True),
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
    )

    op.create_table(
        "inbound_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "folder_id",
            sa.Integer(),
            sa.ForeignKey("inbound_folders.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("remote_id", sa.String(512), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True, index=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("remote_mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "processed", "failed", "not_a_receipt",
                name="inbound_file_status", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "receipt_id",
            sa.Integer(),
            sa.ForeignKey("receipts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
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
        sa.UniqueConstraint("folder_id", "remote_id", name="uq_inbound_file_folder_remote"),
    )

    # source column on receipts already allows free-form strings,
    # but document the new value here for clarity.
    # values: email | upload | api | scanner | cloud_folder


def downgrade() -> None:
    op.drop_table("inbound_files")
    op.drop_table("inbound_folders")
    op.execute("DROP TYPE IF EXISTS inbound_file_status")
    op.execute("DROP TYPE IF EXISTS inbound_folder_type")
