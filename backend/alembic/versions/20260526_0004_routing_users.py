"""org routing rules + multi-user + per-org access

Revision ID: 0004_routing_users
Revises: 0003_accountant
Create Date: 2026-05-26 00:00:00

- organization_routing_rules: shared mailbox → multi-org routing
- users.role: admin | accountant
- user_organizations: scoping accountant accounts to specific orgs
- receipts: drop NOT NULL on filename/file_path (we now create receipt
  candidates before the file exists in some flows)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_routing_users"
down_revision: Union[str, None] = "0003_accountant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # organization_routing_rules
    op.create_table(
        "organization_routing_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_type", sa.String(32), nullable=False),  # body_contains | sender_contains | subject_contains | sender_domain
        sa.Column("match_value", sa.String(512), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_org_routing_organization_id", "organization_routing_rules", ["organization_id"])

    # users.role + per-org access
    op.add_column("users", sa.Column("role", sa.String(32), nullable=False, server_default="admin"))
    op.create_table(
        "user_organizations",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("user_organizations")
    op.drop_column("users", "role")
    op.drop_index("ix_org_routing_organization_id", table_name="organization_routing_rules")
    op.drop_table("organization_routing_rules")
