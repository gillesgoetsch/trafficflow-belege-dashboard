"""Idempotent seed: admin user, global providers + rules, initial orgs + clients.

Run on every container startup. Adding a duplicate is a no-op (UPSERT-by-slug).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.logging import get_logger, setup as setup_logging
from app.core.security import hash_password
from app.db.models import (
    Client,
    MatchType,
    Organization,
    Provider,
    ProviderRule,
    User,
)
from app.db.session import SessionLocal

logger = get_logger(__name__)


# (slug, display, category, default_currency, icon, rules[])
# rules: list of (match_type, match_value, priority)
PROVIDER_SEEDS: list[tuple[str, str, str | None, str | None, str | None, list[tuple[MatchType, str, int]]]] = [
    # ---- TrafficFlow expected providers
    ("infomaniak", "Infomaniak", "Hosting", "CHF", "globe", [
        (MatchType.sender_domain, "infomaniak.com", 120),
        (MatchType.sender_domain, "infomaniak.ch", 120),
    ]),
    ("google-workspace", "Google Workspace", "SaaS", "USD", "google", [
        (MatchType.sender_email, "payments-noreply@google.com", 130),
        (MatchType.subject_contains, "Google Workspace", 110),
    ]),
    ("spotify-ads", "Spotify Ads", "Ads", "EUR", "music", [
        (MatchType.sender_domain, "spotify.com", 110),
        (MatchType.subject_contains, "Spotify Ads", 120),
    ]),
    ("figma", "Figma", "SaaS", "USD", "figma", [
        (MatchType.sender_domain, "figma.com", 130),
        (MatchType.subject_contains, "Figma", 100),
    ]),
    ("adobe", "Adobe Creative Cloud", "SaaS", "USD", "adobe", [
        (MatchType.sender_domain, "adobe.com", 130),
        (MatchType.subject_contains, "Adobe", 100),
    ]),
    ("harvest", "Harvest", "SaaS", "USD", "clock", [
        (MatchType.sender_domain, "getharvest.com", 130),
    ]),
    ("wingo", "Wingo", "Telecom", "CHF", "phone", [
        (MatchType.sender_domain, "wingo.ch", 130),
    ]),
    ("notion", "Notion", "SaaS", "USD", "book", [
        (MatchType.sender_domain, "notion.so", 130),
        (MatchType.sender_domain, "makenotion.com", 130),
    ]),
    ("openai", "OpenAI / ChatGPT", "AI", "USD", "openai", [
        (MatchType.sender_domain, "openai.com", 130),
        (MatchType.subject_contains, "ChatGPT", 110),
    ]),
    ("bexio", "Bexio", "Buchhaltung", "CHF", "calculator", [
        (MatchType.sender_domain, "bexio.com", 130),
    ]),
    ("netcup", "Netcup", "Hosting", "EUR", "server", [
        (MatchType.sender_domain, "netcup.de", 130),
        (MatchType.sender_domain, "netcup.eu", 130),
    ]),
    ("google-one", "Google One", "SaaS", "USD", "google", [
        (MatchType.subject_contains, "Google One", 120),
    ]),
    ("anthropic", "Anthropic / Claude", "AI", "USD", "anthropic", [
        (MatchType.sender_domain, "anthropic.com", 130),
        (MatchType.subject_contains, "Claude", 110),
    ]),
    ("hey-mail", "HEY", "Email", "USD", "mail", [
        (MatchType.sender_domain, "hey.com", 130),
    ]),

    # ---- SicherSatt expected providers
    ("slack", "Slack", "SaaS", "USD", "slack", [
        (MatchType.sender_domain, "slack.com", 130),
    ]),
    ("google-ads", "Google Ads", "Ads", "CHF", "google", [
        (MatchType.sender_email, "payments-noreply@google.com", 130),
        (MatchType.subject_contains, "Google Ads", 120),
    ]),
    ("facebook-ads", "Facebook / Meta Ads", "Ads", "CHF", "facebook", [
        (MatchType.sender_domain, "facebookmail.com", 130),
        (MatchType.sender_domain, "facebook.com", 130),
        (MatchType.subject_contains, "Ihre Rechnung von Meta", 130),
        (MatchType.subject_contains, "Your Facebook ads receipt", 120),
        (MatchType.subject_contains, "Meta Ads", 110),
    ]),
    ("klaviyo", "Klaviyo", "SaaS", "USD", "mail", [
        (MatchType.sender_domain, "klaviyo.com", 130),
    ]),
    ("1password", "1Password", "Security", "USD", "lock", [
        (MatchType.sender_domain, "1password.com", 130),
        (MatchType.sender_domain, "agilebits.com", 130),
    ]),
    ("seranking", "SE Ranking (via 2CO)", "SEO", "USD", "search", [
        (MatchType.sender_domain, "seranking.com", 120),
        (MatchType.sender_domain, "2co.com", 130),
        (MatchType.sender_domain, "2checkout.com", 130),
        (MatchType.subject_contains, "SE Ranking", 110),
    ]),
    ("ewww-io", "EWWW.io", "WordPress", "USD", "image", [
        (MatchType.sender_domain, "ewww.io", 130),
    ]),
    ("hostkey", "Hostkey", "Hosting", "USD", "server", [
        (MatchType.sender_domain, "hostkey.com", 130),
    ]),
]


# (org_name, primary_email, default_currency, [client_slugs])
# Note: "leckker" and "sichersatt" used to be sub-clients of SicherSatt AG.
# They're now treated as BRANDS (lightweight tag on each receipt) since
# they're the same legal client. The migration 0002_payment_brand removes
# the leftover rows.
ORG_SEEDS: list[tuple[str, str, str, list[str]]] = [
    ("TrafficFlow GmbH", "belege@trafficflow.ch", "CHF", []),
    ("SicherSatt AG", "belege@sichersatt.ch", "CHF", []),
    ("kingnature AG", "belege@kingnature.ch", "CHF", []),
]

# (org_name, match_value, match_type)  match_type: subject_contains | sender_contains | body_contains
# Used to route an incoming receipt to the right organization when the same mailbox
# receives bills for multiple companies (e.g. belege@trafficflow.ch also gets Meta
# Ads receipts for kingnature AG and SicherSatt brands).
ORG_ROUTING_SEEDS: list[tuple[str, str, str]] = [
    ("kingnature AG", "kingnature", "body_contains"),
    ("kingnature AG", "FIMS", "body_contains"),
    ("SicherSatt AG", "leckker", "body_contains"),
    ("SicherSatt AG", "sichersatt", "body_contains"),
    ("SicherSatt AG", "Reto", "body_contains"),
]


async def seed_admin(db):
    user = await db.scalar(select(User).where(User.email == settings.admin_email))
    if user:
        return
    db.add(User(
        email=settings.admin_email,
        password_hash=hash_password(settings.admin_password),
        is_admin=True,
        is_active=True,
    ))
    await db.commit()
    logger.info("seed.admin_created", email=str(settings.admin_email))


async def seed_providers(db):
    for slug, display, category, default_currency, icon, rules in PROVIDER_SEEDS:
        prov = await db.scalar(select(Provider).where(Provider.slug == slug))
        if not prov:
            prov = Provider(
                slug=slug, display_name=display, category=category,
                default_currency=default_currency, icon=icon,
            )
            db.add(prov)
            await db.flush()
        # rules
        for mt, mv, prio in rules:
            existing = await db.scalar(select(ProviderRule).where(
                ProviderRule.provider_id == prov.id,
                ProviderRule.organization_id.is_(None),
                ProviderRule.match_type == mt,
                ProviderRule.match_value == mv,
            ))
            if not existing:
                db.add(ProviderRule(
                    provider_id=prov.id, organization_id=None,
                    match_type=mt, match_value=mv, priority=prio,
                ))
    await db.commit()


async def seed_routing(db):
    from app.db.models import OrganizationRoutingRule
    for org_name, value, mtype in ORG_ROUTING_SEEDS:
        org = await db.scalar(select(Organization).where(Organization.name == org_name))
        if not org:
            continue
        existing = await db.scalar(
            select(OrganizationRoutingRule).where(
                OrganizationRoutingRule.organization_id == org.id,
                OrganizationRoutingRule.match_type == mtype,
                OrganizationRoutingRule.match_value == value,
            )
        )
        if not existing:
            db.add(OrganizationRoutingRule(
                organization_id=org.id, match_type=mtype, match_value=value, priority=100,
            ))
    await db.commit()


async def seed_orgs(db):
    for name, email, currency, client_slugs in ORG_SEEDS:
        org = await db.scalar(select(Organization).where(Organization.name == name))
        if not org:
            org = Organization(
                name=name, primary_email=email,
                default_currency=currency,
            )
            db.add(org)
            await db.flush()
            logger.info("seed.org_created", name=name)
        for slug in client_slugs:
            existing = await db.scalar(select(Client).where(
                Client.organization_id == org.id, Client.slug == slug,
            ))
            if not existing:
                db.add(Client(
                    organization_id=org.id,
                    name=slug.capitalize(),
                    slug=slug,
                ))
        await db.commit()


async def main():
    setup_logging()
    async with SessionLocal() as db:
        try:
            await seed_admin(db)
            await seed_providers(db)
            await seed_orgs(db)
            await seed_routing(db)
        except IntegrityError as e:
            await db.rollback()
            logger.error("seed.integrity", error=str(e))
    logger.info("seed.done")


if __name__ == "__main__":
    asyncio.run(main())
