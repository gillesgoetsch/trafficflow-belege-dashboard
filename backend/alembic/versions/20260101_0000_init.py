"""init schema

Revision ID: 0001_init
Revises:
Create Date: 2026-01-01 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums — `create_type=False` so column references don't try to recreate
    # them; we create them explicitly below with checkfirst=True.
    match_type_enum = sa.Enum(
        "sender_domain", "sender_email", "subject_contains", "body_contains",
        "plus_alias", "sender_contains",
        name="match_type", create_type=False,
    )
    classification_layer_enum = sa.Enum("1", "2", "3", "manual", name="classification_layer", create_type=False)
    connector_type_enum = sa.Enum("local", "onedrive", "bexio", name="connector_type", create_type=False)
    receipt_status_enum = sa.Enum(
        "processing", "processed", "review_needed", "archived", "failed",
        name="receipt_status", create_type=False,
    )
    sync_status_enum = sa.Enum("pending", "synced", "failed", "skipped", name="sync_status", create_type=False)
    email_msg_status_enum = sa.Enum(
        "pending", "classified", "rendered", "finished",
        "review_needed", "failed", "not_a_receipt",
        name="email_msg_status", create_type=False,
    )

    # Now actually create them (idempotent thanks to checkfirst=True).

    bind = op.get_bind()
    for enum in (
        match_type_enum, classification_layer_enum, connector_type_enum,
        receipt_status_enum, sync_status_enum, email_msg_status_enum,
    ):
        enum.create(bind, checkfirst=True)

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("totp_secret", sa.String(64)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("primary_email", sa.String(255), nullable=False),
        sa.Column("default_currency", sa.String(8), nullable=False, server_default="CHF"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Zurich"),
        sa.Column(
            "filename_template", sa.String(255), nullable=False,
            server_default="{date}_{provider}_{client}_{amount}-{currency}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # mailboxes
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("imap_host", sa.String(255), nullable=False),
        sa.Column("imap_port", sa.Integer, nullable=False, server_default="993"),
        sa.Column("imap_user", sa.String(255), nullable=False),
        sa.Column("imap_password_enc", sa.Text, nullable=False),
        sa.Column("use_tls", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("folder", sa.String(128), nullable=False, server_default="INBOX"),
        sa.Column("batch_interval_minutes", sa.Integer, nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_uid", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "email", name="uq_org_mailbox_email"),
    )
    op.create_index("ix_mailboxes_organization_id", "mailboxes", ["organization_id"])

    # providers
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64)),
        sa.Column("default_currency", sa.String(8)),
        sa.Column("icon", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # provider_rules
    op.create_table(
        "provider_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider_id", sa.Integer, sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        sa.Column("match_type", match_type_enum, nullable=False),
        sa.Column("match_value", sa.String(512), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_provider_rules_provider_id", "provider_rules", ["provider_id"])
    op.create_index("ix_provider_rules_organization_id", "provider_rules", ["organization_id"])

    # clients
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("color", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "slug", name="uq_org_client_slug"),
    )
    op.create_index("ix_clients_organization_id", "clients", ["organization_id"])

    # client_mappings
    op.create_table(
        "client_mappings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer, sa.ForeignKey("providers.id", ondelete="SET NULL")),
        sa.Column("match_type", match_type_enum, nullable=False),
        sa.Column("match_value", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_client_mappings_client_id", "client_mappings", ["client_id"])

    # email_messages
    op.create_table(
        "email_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mailbox_id", sa.Integer, sa.ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(998), nullable=False),
        sa.Column("imap_uid", sa.BigInteger),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("subject", sa.Text),
        sa.Column("sender_name", sa.String(255)),
        sa.Column("sender_email", sa.String(255)),
        sa.Column("to_address", sa.String(998)),
        sa.Column("raw_size", sa.Integer),
        sa.Column("raw_path", sa.String(512)),
        sa.Column("status", email_msg_status_enum, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("mailbox_id", "message_id", name="uq_mailbox_message_id"),
    )
    op.create_index("ix_email_messages_mailbox_id", "email_messages", ["mailbox_id"])
    op.create_index("ix_email_messages_organization_id", "email_messages", ["organization_id"])
    op.create_index("ix_email_messages_status", "email_messages", ["status"])
    op.create_index("ix_email_msg_received", "email_messages", ["received_at"])

    # receipts
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mailbox_id", sa.Integer, sa.ForeignKey("mailboxes.id", ondelete="SET NULL")),
        sa.Column("email_message_id", sa.Integer, sa.ForeignKey("email_messages.id", ondelete="SET NULL")),
        sa.Column("provider_id", sa.Integer, sa.ForeignKey("providers.id", ondelete="SET NULL")),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("document_date", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(8)),
        sa.Column("invoice_number", sa.String(128)),
        sa.Column("language", sa.String(8)),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("file_size", sa.BigInteger),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("source", sa.String(32), nullable=False, server_default="email"),
        sa.Column("classification_layer", classification_layer_enum, nullable=False, server_default="1"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
        sa.Column("status", receipt_status_enum, nullable=False, server_default="processing"),
        sa.Column("raw_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("processing_log", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("review_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_receipts_organization_id", "receipts", ["organization_id"])
    op.create_index("ix_receipts_status", "receipts", ["status"])
    op.create_index("ix_receipts_org_status_date", "receipts", ["organization_id", "status", "document_date"])
    op.create_index("ix_receipts_provider", "receipts", ["provider_id"])

    # connectors
    op.create_table(
        "connectors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", connector_type_enum, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("config_enc", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_connectors_organization_id", "connectors", ["organization_id"])

    # sync_targets
    op.create_table(
        "sync_targets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("receipt_id", sa.Integer, sa.ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_id", sa.Integer, sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sync_status_enum, nullable=False, server_default="pending"),
        sa.Column("synced_at", sa.DateTime(timezone=True)),
        sa.Column("external_id", sa.String(255)),
        sa.Column("error", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("receipt_id", "connector_id", name="uq_sync_target"),
    )
    op.create_index("ix_sync_targets_receipt_id", "sync_targets", ["receipt_id"])
    op.create_index("ix_sync_targets_connector_id", "sync_targets", ["connector_id"])

    # audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", sa.BigInteger),
        sa.Column("detail", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in (
        "audit_events", "sync_targets", "connectors", "receipts",
        "email_messages", "client_mappings", "clients",
        "provider_rules", "providers", "mailboxes", "organizations", "users",
    ):
        op.drop_table(table)
    for name in (
        "email_msg_status", "sync_status", "receipt_status",
        "connector_type", "classification_layer", "match_type",
    ):
        op.execute(f"DROP TYPE IF EXISTS {name}")
