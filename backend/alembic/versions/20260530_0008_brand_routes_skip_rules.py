"""Brand routing + email skip rules

Revision ID: 0008_brand_routes_skip_rules
Revises: 0007_bexio_sync
Create Date: 2026-05-30 00:00:00

Two new tables:

- email_skip_rules: matches that mean "not a receipt — archive silently".
  Catches Spotify/Meta privacy-policy updates that share a sender with real
  receipts and would otherwise pass Layer 1.

- brand_routes: matches that override the organization on a receipt based on
  body/subject content. Example: a Meta Ads receipt arriving on the
  trafficflow.ch inbox whose body says "Transaction for FIMS" should be
  reassigned to the kingnature org with brand="fims".
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_brand_routes_skip_rules"
down_revision: Union[str, None] = "0007_bexio_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # match_type enum already exists from migration 0001 — reuse it.
    match_type_enum = postgresql.ENUM(
        "sender_domain",
        "sender_email",
        "subject_contains",
        "body_contains",
        "plus_alias",
        "sender_contains",
        name="match_type",
        create_type=False,
    )

    op.create_table(
        "email_skip_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("match_type", match_type_enum, nullable=False),
        sa.Column("match_value", sa.String(512), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
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
        "brand_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "target_organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("match_type", match_type_enum, nullable=False),
        sa.Column("match_value", sa.String(512), nullable=False),
        sa.Column("brand", sa.String(64), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
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

    # ---- Seed Phase 1 -----------------------------------------------------
    # Global non-receipt patterns (apply to all orgs).
    op.execute(
        """
        INSERT INTO email_skip_rules (organization_id, match_type, match_value, reason, priority, created_at, updated_at)
        VALUES
            (NULL, 'subject_contains', 'datenschutzrichtlinie', 'Privacy-policy update — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'datenschutz-aktualisierung', 'Privacy-policy update — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'privacy policy update', 'Privacy-policy update — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'aktualisierung unserer datenschutz', 'Privacy-policy update — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'aktualisierte nutzungsbedingungen', 'Terms-of-service update — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'terms of service', 'Terms-of-service update — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'newsletter', 'Newsletter — not a receipt', 150, now(), now()),
            (NULL, 'body_contains', 'aktualisierte datenschutzrichtlinie', 'Privacy-policy update body — not a receipt', 150, now(), now())
        """
    )

    # FIMS brand route: when a Meta Ads receipt arrives on the TrafficFlow
    # mailbox and body says "Transaction for FIMS", reassign to kingnature.
    op.execute(
        """
        INSERT INTO brand_routes (
            source_organization_id, target_organization_id, provider_id,
            match_type, match_value, brand, priority, created_at, updated_at
        )
        SELECT
            src.id, tgt.id, prov.id,
            'body_contains', 'transaction for fims', 'fims', 200, now(), now()
        FROM organizations src, organizations tgt, providers prov
        WHERE src.name = 'TrafficFlow GmbH'
          AND tgt.name = 'kingnature AG'
          AND prov.slug = 'facebook-ads'
        LIMIT 1
        """
    )


def downgrade() -> None:
    op.drop_table("brand_routes")
    op.drop_table("email_skip_rules")
