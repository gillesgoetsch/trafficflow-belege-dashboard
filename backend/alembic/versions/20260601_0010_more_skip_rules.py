"""More email_skip_rules: verification codes, login-alerts, account notices

Revision ID: 0010_more_skip_rules
Revises: 0009_inbound_folders
Create Date: 2026-06-01 00:00:00

Catches:
- ChatGPT/OpenAI verification code emails ("Enter this temporary verification
  code", "If you were not trying to log in to ChatGPT")
- Generic 2FA / sign-in code emails
- Password reset confirmations
- Account-status / security-alert emails
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0010_more_skip_rules"
down_revision: Union[str, None] = "0009_inbound_folders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO email_skip_rules (organization_id, match_type, match_value, reason, priority, created_at, updated_at)
        VALUES
            -- Verification / 2FA / sign-in codes
            (NULL, 'body_contains',    'verification code',                   'Verification code email — not a receipt', 220, now(), now()),
            (NULL, 'body_contains',    'temporary verification code',         'Verification code email — not a receipt', 230, now(), now()),
            (NULL, 'body_contains',    'if you were not trying to log in',    'Login-alert email — not a receipt',       230, now(), now()),
            (NULL, 'body_contains',    'reset your password',                 'Password reset — not a receipt',          220, now(), now()),
            (NULL, 'body_contains',    'sign-in code',                        'Sign-in code — not a receipt',            220, now(), now()),
            (NULL, 'subject_contains', 'verification code',                   'Verification code subject — not a receipt', 220, now(), now()),
            (NULL, 'subject_contains', 'verify your',                         'Email verification — not a receipt',      210, now(), now()),
            (NULL, 'subject_contains', 'sign-in code',                        'Sign-in code subject — not a receipt',    220, now(), now()),
            (NULL, 'subject_contains', 'login code',                          'Login code subject — not a receipt',      220, now(), now()),
            (NULL, 'subject_contains', 'anmeldecode',                         'German login code — not a receipt',       220, now(), now()),
            (NULL, 'subject_contains', 'bestätigungscode',                    'German confirmation code — not a receipt', 220, now(), now()),
            (NULL, 'subject_contains', 'password reset',                      'Password reset subject — not a receipt',  210, now(), now()),
            (NULL, 'subject_contains', 'passwort zurücksetzen',               'German password reset — not a receipt',   210, now(), now()),
            (NULL, 'subject_contains', 'security alert',                      'Security alert — not a receipt',          200, now(), now()),
            (NULL, 'subject_contains', 'sicherheitswarnung',                  'German security alert — not a receipt',   200, now(), now()),
            (NULL, 'subject_contains', 'new sign-in',                         'New sign-in notice — not a receipt',      200, now(), now()),
            (NULL, 'subject_contains', 'neue anmeldung',                      'German new-login notice — not a receipt', 200, now(), now()),
            (NULL, 'subject_contains', 'welcome to',                          'Welcome email — not a receipt',           150, now(), now()),
            (NULL, 'subject_contains', 'willkommen bei',                      'German welcome email — not a receipt',    150, now(), now())
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM email_skip_rules
        WHERE reason IN (
            'Verification code email — not a receipt',
            'Login-alert email — not a receipt',
            'Password reset — not a receipt',
            'Sign-in code — not a receipt',
            'Verification code subject — not a receipt',
            'Email verification — not a receipt',
            'Sign-in code subject — not a receipt',
            'Login code subject — not a receipt',
            'German login code — not a receipt',
            'German confirmation code — not a receipt',
            'Password reset subject — not a receipt',
            'German password reset — not a receipt',
            'Security alert — not a receipt',
            'German security alert — not a receipt',
            'New sign-in notice — not a receipt',
            'German new-login notice — not a receipt',
            'Welcome email — not a receipt',
            'German welcome email — not a receipt'
        )
        """
    )
