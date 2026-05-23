"""Dashboard KPIs + charts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models import (
    ClassificationLayer,
    Provider,
    Receipt,
    ReceiptStatus,
    SyncStatus,
    SyncTarget,
    User,
)
from app.db.session import get_db
from app.schemas import DashboardCharts, DashboardKPIs, PaymentMethodShare, ProviderShare, TimeSeriesPoint

router = APIRouter()


def _month_range(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return start, nxt


@router.get("/kpis", response_model=DashboardKPIs)
async def kpis(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
):
    base = select(Receipt)
    if organization_id:
        base = base.where(Receipt.organization_id == organization_id)

    now = datetime.now(UTC)
    this_start, next_start = _month_range(now)
    last_start = (this_start - timedelta(days=1)).replace(day=1)

    receipts_total = await db.scalar(
        select(func.count()).select_from(Receipt).where(*(
            [Receipt.organization_id == organization_id] if organization_id else []
        ))
    ) or 0

    def _cnt(start, end):
        q = select(func.count()).select_from(Receipt).where(
            Receipt.document_date >= start, Receipt.document_date < end,
            Receipt.status != ReceiptStatus.archived,
        )
        if organization_id:
            q = q.where(Receipt.organization_id == organization_id)
        return q

    receipts_this_month = await db.scalar(_cnt(this_start, next_start)) or 0
    receipts_last_month = await db.scalar(_cnt(last_start, this_start)) or 0

    amount_q = select(func.coalesce(func.sum(Receipt.amount), 0)).where(
        Receipt.document_date >= this_start,
        Receipt.document_date < next_start,
        Receipt.status == ReceiptStatus.processed,
    )
    if organization_id:
        amount_q = amount_q.where(Receipt.organization_id == organization_id)
    total_amount_this_month = await db.scalar(amount_q) or 0

    review_q = select(func.count()).select_from(Receipt).where(Receipt.status == ReceiptStatus.review_needed)
    if organization_id:
        review_q = review_q.where(Receipt.organization_id == organization_id)
    review_queue_size = await db.scalar(review_q) or 0

    sync_failed_q = (
        select(func.count())
        .select_from(SyncTarget)
        .join(Receipt, Receipt.id == SyncTarget.receipt_id)
        .where(SyncTarget.status == SyncStatus.failed)
    )
    if organization_id:
        sync_failed_q = sync_failed_q.where(Receipt.organization_id == organization_id)
    sync_failed_count = await db.scalar(sync_failed_q) or 0

    layer_dist_q = select(Receipt.classification_layer, func.count()).group_by(Receipt.classification_layer)
    if organization_id:
        layer_dist_q = layer_dist_q.where(Receipt.organization_id == organization_id)
    layer_distribution = {layer.value if hasattr(layer, "value") else str(layer): cnt
                          for layer, cnt in (await db.execute(layer_dist_q)).all()}

    return DashboardKPIs(
        receipts_total=receipts_total,
        receipts_this_month=receipts_this_month,
        receipts_last_month=receipts_last_month,
        total_amount_this_month=total_amount_this_month,
        review_queue_size=review_queue_size,
        sync_failed_count=sync_failed_count,
        layer_distribution=layer_distribution,
    )


@router.get("/charts", response_model=DashboardCharts)
async def charts(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
    days: int = 90,
):
    since = datetime.now(UTC) - timedelta(days=days)
    bucket = func.date_trunc("day", Receipt.document_date).label("bucket")
    q = (
        select(bucket, func.count().label("c"))
        .where(Receipt.document_date >= since, Receipt.status != ReceiptStatus.archived)
        .group_by(bucket)
        .order_by(bucket)
    )
    if organization_id:
        q = q.where(Receipt.organization_id == organization_id)
    by_day = [TimeSeriesPoint(bucket=b.date().isoformat() if b else "", value=float(c))
              for b, c in (await db.execute(q)).all()]

    top_q = (
        select(Provider.id, Provider.display_name, func.count(Receipt.id), func.coalesce(func.sum(Receipt.amount), 0))
        .join(Receipt, Receipt.provider_id == Provider.id)
        .where(Receipt.document_date >= since, Receipt.status == ReceiptStatus.processed)
        .group_by(Provider.id, Provider.display_name)
        .order_by(func.count(Receipt.id).desc())
        .limit(10)
    )
    if organization_id:
        top_q = top_q.where(Receipt.organization_id == organization_id)
    top_providers = [
        ProviderShare(provider_id=pid, provider=name, count=cnt, total_amount=amt)
        for pid, name, cnt, amt in (await db.execute(top_q)).all()
    ]

    pm_q = (
        select(Receipt.payment_method, func.count(), func.coalesce(func.sum(Receipt.amount), 0))
        .where(Receipt.document_date >= since, Receipt.status == ReceiptStatus.processed)
        .group_by(Receipt.payment_method)
    )
    if organization_id:
        pm_q = pm_q.where(Receipt.organization_id == organization_id)
    by_payment_method = [
        PaymentMethodShare(
            payment_method=pm.value if hasattr(pm, "value") else str(pm),
            count=cnt, total_amount=amt,
        )
        for pm, cnt, amt in (await db.execute(pm_q)).all()
    ]

    return DashboardCharts(by_day=by_day, top_providers=top_providers, by_payment_method=by_payment_method)
