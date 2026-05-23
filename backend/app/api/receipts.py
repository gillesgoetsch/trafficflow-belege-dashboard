"""Receipt list/detail/edit/reprocess/bulk endpoints + file download + ZIP/CSV export."""
from __future__ import annotations

import csv
import io
import os
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from arq.connections import create_pool, RedisSettings
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.pagination import Page, page_params
from app.core.security import get_current_user
from app.db.models import Client, Organization, PaymentMethod, Provider, Receipt, ReceiptStatus, User
from app.db.session import get_db
from app.schemas import ReceiptDetail, ReceiptListOut, ReceiptOut, ReceiptPatch

router = APIRouter()


def _filter_query(
    organization_id: int | None,
    mailbox_id: int | None,
    provider_id: int | None,
    client_id: int | None,
    status_: ReceiptStatus | None,
    payment_method: PaymentMethod | None,
    brand: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
    search: str | None,
    booked: str | None = None,  # "yes" | "no" | None
):
    conds = []
    if organization_id:
        conds.append(Receipt.organization_id == organization_id)
    if mailbox_id:
        conds.append(Receipt.mailbox_id == mailbox_id)
    if provider_id:
        conds.append(Receipt.provider_id == provider_id)
    if client_id:
        conds.append(Receipt.client_id == client_id)
    if status_:
        conds.append(Receipt.status == status_)
    if payment_method:
        conds.append(Receipt.payment_method == payment_method)
    if brand:
        conds.append(Receipt.brand == brand)
    if booked == "yes":
        conds.append(Receipt.booked_at.is_not(None))
    elif booked == "no":
        conds.append(Receipt.booked_at.is_(None))
    if date_from:
        conds.append(Receipt.document_date >= date_from)
    if date_to:
        conds.append(Receipt.document_date <= date_to)
    if amount_min is not None:
        conds.append(Receipt.amount >= amount_min)
    if amount_max is not None:
        conds.append(Receipt.amount <= amount_max)
    if search:
        pattern = f"%{search}%"
        conds.append(or_(
            Receipt.filename.ilike(pattern),
            Receipt.invoice_number.ilike(pattern),
            Receipt.brand.ilike(pattern),
        ))
    return and_(*conds) if conds else True


@router.get("", response_model=ReceiptListOut)
async def list_receipts(
    page: Annotated[Page, Depends(page_params)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
    mailbox_id: int | None = None,
    provider_id: int | None = None,
    client_id: int | None = None,
    status: ReceiptStatus | None = None,
    payment_method: PaymentMethod | None = None,
    brand: str | None = None,
    booked: str | None = Query(None, description="yes | no"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    search: str | None = None,
    sort: str = Query("document_date"),
    order: str = Query("desc"),
):
    cond = _filter_query(organization_id, mailbox_id, provider_id, client_id, status,
                         payment_method, brand,
                         date_from, date_to, amount_min, amount_max, search, booked)

    sort_col_map = {
        "document_date": Receipt.document_date,
        "received_at": Receipt.received_at,
        "amount": Receipt.amount,
        "filename": Receipt.filename,
        "status": Receipt.status,
        "created_at": Receipt.created_at,
    }
    sort_col = sort_col_map.get(sort, Receipt.document_date)
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()

    total = await db.scalar(select(func.count()).select_from(Receipt).where(cond))

    q = (
        select(Receipt)
        .where(cond)
        .order_by(sort_expr, Receipt.id.desc())
        .offset(page.offset)
        .limit(page.limit)
    )
    items = (await db.scalars(q)).all()
    return ReceiptListOut(items=items, total=total or 0, page=page.page, page_size=page.page_size)


@router.get("/{receipt_id}", response_model=ReceiptDetail)
async def get_receipt(
    receipt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.scalar(
        select(Receipt).options(selectinload(Receipt.sync_targets)).where(Receipt.id == receipt_id)
    )
    if not r:
        raise HTTPException(404, "Not found")
    return r


@router.patch("/{receipt_id}", response_model=ReceiptDetail)
async def update_receipt(
    receipt_id: int,
    body: ReceiptPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404, "Not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(r, k, v)
    if data:
        log = list(r.processing_log or [])
        log.append({"ts": datetime.utcnow().isoformat(), "event": "manual_edit", "fields": list(data.keys())})
        r.processing_log = log
    await db.commit()
    await db.refresh(r)
    return await get_receipt(receipt_id, db, _)


@router.get("/{receipt_id}/file")
async def download_file(
    receipt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404, "Not found")
    if not os.path.exists(r.file_path):
        raise HTTPException(410, "File missing on disk")
    media = "application/pdf"
    ext = os.path.splitext(r.filename)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".gif": "image/gif"}[ext]
    return FileResponse(
        r.file_path, media_type=media,
        headers={"Content-Disposition": f'inline; filename="{r.filename}"'},
    )


@router.post("/{receipt_id}/reprocess")
async def reprocess(
    receipt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(Receipt, receipt_id)
    if not r or not r.email_message_id:
        raise HTTPException(404, "Not found or has no source email")
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await pool.enqueue_job("process_message", r.email_message_id, force=True)
    return {"ok": True}


@router.post("/{receipt_id}/resync")
async def resync(
    receipt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    connector_id: int | None = None,
):
    r = await db.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404, "Not found")
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    if connector_id:
        await pool.enqueue_job("sync_receipt_to_connector", r.id, connector_id)
    else:
        await pool.enqueue_job("sync_receipt_all_connectors", r.id)
    return {"ok": True}


@router.post("/bulk/zip")
async def bulk_zip(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    ids: list[int] = Body(..., embed=True),
):
    if not ids or len(ids) > 1000:
        raise HTTPException(400, "Provide 1-1000 receipt IDs")
    rows = (await db.scalars(
        select(Receipt).options(selectinload(Receipt.provider)).where(Receipt.id.in_(ids))
    )).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            if not os.path.exists(r.file_path):
                continue
            year = (r.document_date or r.received_at or r.created_at).year
            month = (r.document_date or r.received_at or r.created_at).month
            arcname = f"{r.organization_id}/{year}/{month:02d}/{r.filename}"
            zf.write(r.file_path, arcname=arcname)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="receipts-{datetime.utcnow():%Y%m%d-%H%M%S}.zip"'},
    )


@router.post("/bulk/reprocess")
async def bulk_reprocess(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    ids: list[int] = Body(..., embed=True),
):
    rows = (await db.scalars(select(Receipt).where(Receipt.id.in_(ids)))).all()
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    for r in rows:
        if r.email_message_id:
            await pool.enqueue_job("process_message", r.email_message_id, force=True)
    return {"ok": True, "count": sum(1 for r in rows if r.email_message_id)}


@router.post("/bulk/resync")
async def bulk_resync(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    ids: list[int] = Body(..., embed=True),
):
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    for rid in ids:
        await pool.enqueue_job("sync_receipt_all_connectors", rid)
    return {"ok": True, "count": len(ids)}


@router.post("/bulk/delete", status_code=204)
async def bulk_delete(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    ids: list[int] = Body(..., embed=True),
):
    rows = (await db.scalars(select(Receipt).where(Receipt.id.in_(ids)))).all()
    for r in rows:
        await db.delete(r)
    await db.commit()


# --- Accountant workflows --------------------------------------------------


@router.post("/{receipt_id}/book")
async def book(
    receipt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    bookkeeping_ref: str | None = Body(None, embed=True),
):
    r = await db.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404, "Not found")
    r.booked_at = datetime.now(UTC)
    if bookkeeping_ref:
        r.bookkeeping_ref = bookkeeping_ref
    await db.commit()
    return {"ok": True, "booked_at": r.booked_at.isoformat()}


@router.post("/{receipt_id}/unbook")
async def unbook(
    receipt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404, "Not found")
    r.booked_at = None
    r.bookkeeping_ref = None
    await db.commit()
    return {"ok": True}


@router.post("/bulk/book")
async def bulk_book(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    ids: list[int] = Body(..., embed=True),
):
    now = datetime.now(UTC)
    rows = (await db.scalars(select(Receipt).where(Receipt.id.in_(ids)))).all()
    for r in rows:
        r.booked_at = now
    await db.commit()
    return {"ok": True, "count": len(rows)}


@router.get("/export/csv")
async def export_csv(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
    provider_id: int | None = None,
    status: ReceiptStatus | None = None,
    payment_method: PaymentMethod | None = None,
    brand: str | None = None,
    booked: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
):
    """Export receipts as CSV — bookkeeping-friendly columns."""
    cond = _filter_query(
        organization_id, None, provider_id, None, status, payment_method, brand,
        date_from, date_to, None, None, search, booked,
    )

    rows = (await db.scalars(
        select(Receipt)
        .options(selectinload(Receipt.provider), selectinload(Receipt.client))
        .where(cond)
        .order_by(Receipt.document_date.asc())
    )).all()

    orgs = {o.id: o.name for o in (await db.scalars(select(Organization))).all()}

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow([
        "ID", "Date", "Organization", "Provider", "Brand", "Client",
        "Amount", "Currency", "VAT rate", "VAT amount",
        "Payment method", "Invoice number", "Filename",
        "Status", "Booked", "Booked at", "Bookkeeping ref", "Notes",
    ])
    for r in rows:
        w.writerow([
            r.id,
            (r.document_date.date().isoformat() if r.document_date else ""),
            orgs.get(r.organization_id, ""),
            (r.provider.display_name if r.provider else ""),
            r.brand or "",
            (r.client.name if r.client else ""),
            (f"{r.amount:.2f}" if r.amount is not None else ""),
            r.currency or "",
            (f"{r.vat_rate:.2f}" if r.vat_rate is not None else ""),
            (f"{r.vat_amount:.2f}" if r.vat_amount is not None else ""),
            r.payment_method.value if hasattr(r.payment_method, "value") else r.payment_method,
            r.invoice_number or "",
            r.filename,
            r.status.value if hasattr(r.status, "value") else r.status,
            "yes" if r.booked_at else "no",
            (r.booked_at.isoformat() if r.booked_at else ""),
            r.bookkeeping_ref or "",
            (r.notes or "").replace("\n", " ").replace("\r", " "),
        ])

    csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens it correctly
    fn = f"receipts-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )
