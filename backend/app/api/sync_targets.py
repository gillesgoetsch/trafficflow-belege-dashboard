"""Sync target inspector — list, detail, promote dry-run → live, manual retry.

Backs the Settings → Bexio Sync Inspector page. Every outbound connector call
writes its full request/response payload to the sync_target so this endpoint
can replay it for the user.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.security import get_current_user
from app.db.models import (
    Connector,
    ConnectorMode,
    Provider,
    Receipt,
    SyncStatus,
    SyncTarget,
    User,
)
from app.db.session import get_db

router = APIRouter()


async def _redis() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


def _row(st: SyncTarget, *, include_payloads: bool = False) -> dict[str, Any]:
    receipt = st.receipt
    connector = st.connector
    provider = receipt.provider if receipt else None
    row = {
        "id": st.id,
        "receipt_id": st.receipt_id,
        "connector_id": st.connector_id,
        "connector_name": connector.name if connector else None,
        "connector_type": connector.type.value if connector else None,
        "organization_id": connector.organization_id if connector else None,
        "status": st.status.value,
        "mode": st.mode.value if st.mode else None,
        "synced_at": st.synced_at.isoformat() if st.synced_at else None,
        "external_id": st.external_id,
        "error": st.error,
        "response_status_code": st.response_status_code,
        "retry_count": st.retry_count,
        "next_retry_at": st.next_retry_at.isoformat() if st.next_retry_at else None,
        "created_at": st.created_at.isoformat() if st.created_at else None,
        "updated_at": st.updated_at.isoformat() if st.updated_at else None,
        "receipt": {
            "id": receipt.id if receipt else None,
            "filename": receipt.filename if receipt else None,
            "amount": str(receipt.amount) if receipt and receipt.amount is not None else None,
            "currency": receipt.currency if receipt else None,
            "invoice_number": receipt.invoice_number if receipt else None,
            "document_date": (
                receipt.document_date.isoformat()
                if receipt and receipt.document_date else None
            ),
            "provider": provider.display_name if provider else None,
        } if receipt else None,
    }
    if include_payloads:
        row["request_payload"] = st.request_payload
        row["response_payload"] = st.response_payload
    return row


@router.get("")
async def list_sync_targets(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
    connector_id: int | None = None,
    status: str | None = None,
    mode: str | None = None,
    receipt_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    q = (
        select(SyncTarget)
        .options(
            selectinload(SyncTarget.receipt).selectinload(Receipt.provider),
            selectinload(SyncTarget.connector),
        )
        .order_by(SyncTarget.updated_at.desc())
    )
    if organization_id:
        q = q.join(Connector, SyncTarget.connector_id == Connector.id).where(
            Connector.organization_id == organization_id
        )
    if connector_id:
        q = q.where(SyncTarget.connector_id == connector_id)
    if status:
        try:
            q = q.where(SyncTarget.status == SyncStatus(status))
        except ValueError:
            raise HTTPException(400, f"invalid status: {status}")
    if mode:
        try:
            q = q.where(SyncTarget.mode == ConnectorMode(mode))
        except ValueError:
            raise HTTPException(400, f"invalid mode: {mode}")
    if receipt_id:
        q = q.where(SyncTarget.receipt_id == receipt_id)
    if since:
        q = q.where(SyncTarget.updated_at >= since)
    if until:
        q = q.where(SyncTarget.updated_at <= until)

    # crude pagination — count separately
    from sqlalchemy import func as _func
    count_q = q.with_only_columns(_func.count(SyncTarget.id)).order_by(None)
    total = (await db.scalars(count_q)).first() or 0

    rows = (await db.scalars(
        q.offset((page - 1) * page_size).limit(page_size)
    )).all()
    return {
        "items": [_row(st) for st in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{sync_target_id}")
async def get_sync_target(
    sync_target_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    q = (
        select(SyncTarget)
        .where(SyncTarget.id == sync_target_id)
        .options(
            selectinload(SyncTarget.receipt).selectinload(Receipt.provider),
            selectinload(SyncTarget.connector),
        )
    )
    st = (await db.scalars(q)).first()
    if not st:
        raise HTTPException(404, "Not found")
    return _row(st, include_payloads=True)


@router.post("/{sync_target_id}/promote")
async def promote_sync_target(
    sync_target_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Re-run this sync target in live mode regardless of connector's current mode.

    Used for promoting a dry-run that the user has validated. Returns 202.
    """
    st = await db.get(SyncTarget, sync_target_id)
    if not st:
        raise HTTPException(404, "Not found")
    redis = await _redis()
    try:
        await redis.enqueue_job(
            "sync_receipt_to_connector",
            st.receipt_id, st.connector_id, "live",
            _job_id=f"promote:{st.receipt_id}:{st.connector_id}:{datetime.utcnow().timestamp()}",
        )
    finally:
        await redis.close()
    return {"ok": True, "queued": True, "mode": "live"}


@router.post("/{sync_target_id}/retry")
async def retry_sync_target(
    sync_target_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Manually re-enqueue this sync target in the connector's current mode.

    Resets the backoff so the worker picks it up immediately.
    """
    st = await db.get(SyncTarget, sync_target_id)
    if not st:
        raise HTTPException(404, "Not found")
    st.retry_count = 0
    st.next_retry_at = None
    await db.commit()
    redis = await _redis()
    try:
        await redis.enqueue_job(
            "sync_receipt_to_connector",
            st.receipt_id, st.connector_id,
            _job_id=f"retry:{st.receipt_id}:{st.connector_id}:{datetime.utcnow().timestamp()}",
        )
    finally:
        await redis.close()
    return {"ok": True, "queued": True}
