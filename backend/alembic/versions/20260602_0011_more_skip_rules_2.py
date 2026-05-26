"""More email_skip_rules: link-only notifications, account invites, mailbox welcome emails

Revision ID: 0011_more_skip_rules_2
Revises: 0010_more_skip_rules
Create Date: 2026-06-02 00:00:00

Catches the SicherSatt-inbox patterns the user flagged:
- Klaviyo "Thanks for your payment / View or download invoice" emails
  from marketing-responses@klaviyo.com (real invoice arrives via Stripe
  attachment separately).
- Infomaniak "Bienvenue sur votre boîte mail professionnelle" welcome.
- Meta/Facebook business-portfolio invite (notification@facebookmail.com)
  vs real Meta Ads receipts (noreply@business-updates.facebook.com).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0011_more_skip_rules_2"
down_revision: Union[str, None] = "0010_more_skip_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO email_skip_rules (organization_id, match_type, match_value, reason, priority, created_at, updated_at)
        VALUES
            -- Klaviyo "Thanks for your payment" marketing copy (real invoice
            -- comes via Stripe with the actual amount in the attachment).
            (NULL, 'sender_email',     'marketing-responses@klaviyo.com',     'Klaviyo marketing channel — duplicate of Stripe receipt', 230, now(), now()),
            (NULL, 'body_contains',    'view or download invoice',            'Link-only invoice notification — amount lives on Stripe link', 200, now(), now()),
            (NULL, 'body_contains',    'thanks for your payment',             'Stripe receipt confirmation only — duplicate of real invoice', 180, now(), now()),

            -- Account invitations / business-portfolio invites (Meta)
            (NULL, 'subject_contains', 'you''ve been invited to join',        'Account invitation — not a receipt', 220, now(), now()),
            (NULL, 'subject_contains', 'business portfolio',                  'Business portfolio invite — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'einladung annehmen',                  'German account invitation — not a receipt', 220, now(), now()),
            (NULL, 'body_contains',    'einladung annehmen und mein konto anlegen', 'German account-invite body — not a receipt', 230, now(), now()),
            (NULL, 'sender_email',     'notification@facebookmail.com',       'Facebook notifications channel — not Meta Ads receipts', 200, now(), now()),

            -- Infomaniak welcome / mailbox setup
            (NULL, 'subject_contains', 'bienvenue sur votre boîte mail',      'Infomaniak mailbox welcome — not a receipt', 220, now(), now()),
            (NULL, 'subject_contains', 'willkommen auf ihrer professionellen mail', 'German mailbox welcome — not a receipt', 220, now(), now())
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM email_skip_rules
        WHERE reason IN (
            'Klaviyo marketing channel — duplicate of Stripe receipt',
            'Link-only invoice notification — amount lives on Stripe link',
            'Stripe receipt confirmation only — duplicate of real invoice',
            'Account invitation — not a receipt',
            'Business portfolio invite — not a receipt',
            'German account invitation — not a receipt',
            'German account-invite body — not a receipt',
            'Facebook notifications channel — not Meta Ads receipts',
            'Infomaniak mailbox welcome — not a receipt',
            'German mailbox welcome — not a receipt'
        )
        """
    )
