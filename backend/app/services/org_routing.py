"""Route an incoming receipt to the right organization.

Multiple legal entities can share a mailbox (e.g. belege@trafficflow.ch also
receives Meta Ads invoices for kingnature AG and SicherSatt brands). This
service applies admin-configurable rules to pick the correct org.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models import Organization, OrganizationRoutingRule


@dataclass
class RoutingInput:
    sender_email: str | None
    subject: str | None
    body_text: str | None
    customer_hint: str | None = None     # vendor's extracted "billed-to" name
    default_organization_id: int | None = None  # fallback if no rules match


async def route(db: AsyncSession, inp: RoutingInput) -> int | None:
    """Return the organization_id this receipt should belong to.

    Rules are evaluated highest priority first. Each rule has match_type +
    match_value; the matcher is case-insensitive substring.
    """
    rules = (await db.scalars(
        select(OrganizationRoutingRule).order_by(OrganizationRoutingRule.priority.desc())
    )).all()

    body = (inp.body_text or "").lower()
    sender = (inp.sender_email or "").lower()
    subject = (inp.subject or "").lower()
    hint = (inp.customer_hint or "").lower()

    for r in rules:
        v = (r.match_value or "").lower().strip()
        if not v:
            continue
        hit = False
        if r.match_type == "body_contains":
            hit = v in body or v in hint
        elif r.match_type == "sender_contains":
            hit = v in sender
        elif r.match_type == "subject_contains":
            hit = v in subject
        elif r.match_type == "sender_domain":
            hit = sender.endswith(v)
        if hit:
            return r.organization_id
    return inp.default_organization_id
