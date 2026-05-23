"""Review queue: list pending review receipts + decide endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.core.security import get_current_user
from app.db.models import (
    ClassificationLayer,
    EmailMessage,
    MatchType,
    Provider,
    ProviderRule,
    Receipt,
    ReceiptStatus,
    User,
)
from app.db.session import get_db
from app.schemas import ReviewDecision, ReviewItemOut

router = APIRouter()


@router.get("", response_model=list[ReviewItemOut])
async def list_review_queue(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
    limit: int = 100,
):
    q = (
        select(Receipt, EmailMessage)
        .join(EmailMessage, EmailMessage.id == Receipt.email_message_id, isouter=True)
        .where(Receipt.status == ReceiptStatus.review_needed)
        .order_by(Receipt.received_at.desc().nulls_last())
        .limit(limit)
    )
    if organization_id:
        q = q.where(Receipt.organization_id == organization_id)

    items: list[ReviewItemOut] = []
    for r, msg in (await db.execute(q)).all():
        prov_slug = None
        if r.provider_id:
            prov = await db.get(Provider, r.provider_id)
            prov_slug = prov.slug if prov else None
        # For email receipts: subject + sender. For uploads: filename + source.
        subject = (msg.subject if msg else None) or r.filename
        sender = ((msg.sender_email or msg.sender_name) if msg else None) or (
            f"upload · {r.payment_method.value if hasattr(r.payment_method, 'value') else r.payment_method}"
        )
        items.append(ReviewItemOut(
            receipt_id=r.id,
            organization_id=r.organization_id,
            subject=subject,
            sender=sender,
            received_at=r.received_at or r.created_at,
            suggested_provider_id=r.provider_id,
            suggested_provider_slug=prov_slug,
            confidence=float(r.confidence or 0),
            amount=r.amount,
            currency=r.currency,
            payment_method=r.payment_method.value if hasattr(r.payment_method, "value") else str(r.payment_method),
            brand=r.brand,
            reason=r.review_reason,
        ))
    return items


@router.post("/{receipt_id}/decide")
async def decide(
    receipt_id: int,
    body: ReviewDecision,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.scalar(
        select(Receipt).options(joinedload(Receipt.email_message)).where(Receipt.id == receipt_id)
    )
    if not r:
        raise HTTPException(404, "Not found")

    if body.action == "reject":
        r.status = ReceiptStatus.archived
        r.review_reason = "marked_not_receipt"
    elif body.action in ("accept", "reassign"):
        if body.provider_id:
            r.provider_id = body.provider_id
        if body.organization_id is not None:
            r.organization_id = body.organization_id
        if body.client_id is not None:
            r.client_id = body.client_id
        r.status = ReceiptStatus.processed
        r.classification_layer = ClassificationLayer.manual
        r.confidence = 1.0
        if body.create_rule and r.email_message and body.provider_id and r.email_message.sender_email:
            domain = r.email_message.sender_email.split("@")[-1].lower()
            existing = await db.scalar(select(ProviderRule).where(
                ProviderRule.provider_id == body.provider_id,
                ProviderRule.match_type == MatchType.sender_domain,
                ProviderRule.match_value == domain,
            ))
            if not existing:
                db.add(ProviderRule(
                    provider_id=body.provider_id,
                    organization_id=r.organization_id,
                    match_type=MatchType.sender_domain,
                    match_value=domain,
                    priority=120,
                ))
    else:
        raise HTTPException(400, "Unknown action")

    log = list(r.processing_log or [])
    log.append({
        "ts": datetime.utcnow().isoformat(),
        "event": "review_decision",
        "action": body.action,
        "provider_id": body.provider_id,
        "organization_id": body.organization_id,
        "client_id": body.client_id,
        "created_rule": body.create_rule,
    })
    r.processing_log = log
    await db.commit()
    return {"ok": True}
