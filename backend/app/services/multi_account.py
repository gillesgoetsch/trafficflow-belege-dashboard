"""Resolve sub-client (e.g. leckker vs sichersatt) for receipts.

Strategy (in order):
1. Plus-alias in the To: header (`belege+leckker@trafficflow.ch`)
2. Configured `client_mappings` (sender_contains / subject_contains / body_contains)
3. Heuristic: match client name in body text
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models import Client, ClientMapping, MatchType


@dataclass
class ResolveInput:
    organization_id: int
    provider_id: int | None
    to_address: str | None
    sender_email: str | None
    subject: str | None
    body_text: str | None


async def resolve_client(db: AsyncSession, inp: ResolveInput) -> Client | None:
    clients = (await db.scalars(select(Client).where(Client.organization_id == inp.organization_id))).all()
    if not clients:
        return None

    # 1) plus-alias
    if inp.to_address:
        # Extract +tag from `local+tag@domain`
        match = re.search(r"\+([\w\-\.]+)@", inp.to_address)
        if match:
            tag = match.group(1).lower()
            for c in clients:
                if c.slug.lower() == tag or c.name.lower() == tag:
                    return c

    # 2) configured mappings
    mappings = (await db.scalars(
        select(ClientMapping).where(
            ClientMapping.client_id.in_([c.id for c in clients])
        )
    )).all()

    haystacks = {
        MatchType.sender_contains: (inp.sender_email or "").lower(),
        MatchType.subject_contains: (inp.subject or "").lower(),
        MatchType.body_contains: (inp.body_text or "").lower(),
        MatchType.plus_alias: (inp.to_address or "").lower(),
    }

    for m in mappings:
        if inp.provider_id and m.provider_id and m.provider_id != inp.provider_id:
            continue
        target = haystacks.get(m.match_type)
        if target and m.match_value and m.match_value.lower() in target:
            return next((c for c in clients if c.id == m.client_id), None)

    # 3) heuristic: client name appears in subject or body
    body_lower = (inp.body_text or "").lower()
    subject_lower = (inp.subject or "").lower()
    for c in clients:
        nm = c.name.lower()
        if len(nm) < 3:
            continue
        if nm in subject_lower or nm in body_lower:
            return c
    return None
