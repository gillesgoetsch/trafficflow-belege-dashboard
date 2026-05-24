"""Receipt list/detail/edit/reprocess/bulk endpoints + file download + ZIP/CSV export."""
from __future__ import annotations

import csv
import io
import os
import re
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
    date_field: str = "document_date",  # "document_date" | "received_at"
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
    # The date filter can apply to document_date (the invoice's own date) or
    # received_at (when it landed in the system). The latter is what you want
    # when filtering for "scanned this quarter" — old documents like a
    # Fahrzeugausweis from 2008 only need to appear under Q-of-upload.
    date_col = Receipt.received_at if date_field == "received_at" else Receipt.document_date
    if date_from:
        conds.append(date_col >= date_from)
    if date_to:
        conds.append(date_col <= date_to)
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
    date_field: str = Query("document_date", description="document_date | received_at"),
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    search: str | None = None,
    sort: str = Query("document_date"),
    order: str = Query("desc"),
):
    cond = _filter_query(organization_id, mailbox_id, provider_id, client_id, status,
                         payment_method, brand,
                         date_from, date_to, amount_min, amount_max, search, booked,
                         date_field=date_field)

    sort_col_map = {
        "document_date": Receipt.document_date,
        "due_date": Receipt.due_date,
        "received_at": Receipt.received_at,
        "amount": Receipt.amount,
        "filename": Receipt.filename,
        "status": Receipt.status,
        "created_at": Receipt.created_at,
        "provider_id": Receipt.provider_id,
        "payment_method": Receipt.payment_method,
        "brand": Receipt.brand,
        "booked_at": Receipt.booked_at,
        "document_type": Receipt.document_type,
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
    engine: str = "auto",
):
    """Re-run extraction on a single receipt.

    engine:
      - "api"   : always use Claude (network call, ~$0.005)
      - "local" : always use the local Qwen LLM (free, slower, less accurate)
      - "auto"  : local first; fall back to Claude on low confidence

    Works for both email-sourced and uploaded receipts.
    """
    if engine not in ("api", "local", "auto"):
        raise HTTPException(400, "engine must be one of: api, local, auto")
    r = await db.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404, "Not found")
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    if r.email_message_id:
        # email pipeline always uses Claude (the receipt path here doesn't yet
        # support local extraction for email-sourced bodies).
        await pool.enqueue_job("process_message", r.email_message_id, force=True)
        kind = "process_message"
    else:
        await pool.enqueue_job("process_uploaded_receipt", r.id, engine)
        kind = f"process_uploaded_receipt({engine})"
    return {"ok": True, "kind": kind, "engine": engine}


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


def _safe_seg(s: str | None, fallback: str = "Unknown") -> str:
    import re as _re
    if not s:
        return fallback
    out = _re.sub(r"[^A-Za-z0-9._\-()\s]", "_", s).strip()[:80]
    return out or fallback


@router.post("/bulk/zip")
async def bulk_zip(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    ids: list[int] = Body(..., embed=True),
):
    """ZIP up the selected receipts with a bookkeeping-friendly folder structure:

    {Organization}/
      Credit-card/
        {Provider}/
          YYYY-MM-DD_Provider_Amount-Currency.pdf
      Bank-transfer/
        YYYY-MM-DD_Provider_Amount-Currency.pdf
      Twint/, Cash/, ... (other payment methods)

    Bank-transfer receipts are consolidated in one folder per organization
    (they're usually rare and recipients often unique); credit-card receipts
    are grouped by provider since they tend to be recurring subscriptions.
    """
    if not ids or len(ids) > 5000:
        raise HTTPException(400, "Provide 1-5000 receipt IDs")
    rows = (await db.scalars(
        select(Receipt)
        .options(selectinload(Receipt.provider))
        .where(Receipt.id.in_(ids))
    )).all()

    orgs = {o.id: o for o in (await db.scalars(select(Organization))).all()}

    # Date-range label for the root folder (e.g. "2026 Q1", "2026-04",
    # "2025-2026" depending on the span of receipts in this zip).
    dates = [
        (r.document_date or r.received_at or r.created_at) for r in rows
        if (r.document_date or r.received_at or r.created_at)
    ]
    if dates:
        d_min, d_max = min(dates), max(dates)
        if d_min.year == d_max.year:
            year = d_min.year
            q_min, q_max = (d_min.month - 1) // 3 + 1, (d_max.month - 1) // 3 + 1
            if d_min.month == d_max.month:
                range_label = f"{year}-{d_min.month:02d}"
            elif q_min == q_max:
                range_label = f"{year} Q{q_min}"
            else:
                range_label = f"{year} Q{q_min}-Q{q_max}"
        else:
            range_label = f"{d_min.year}-{d_max.year}"
    else:
        range_label = "Export"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            if not os.path.exists(r.file_path):
                continue
            org = orgs.get(r.organization_id)
            org_name = _safe_seg(org.name if org else f"org-{r.organization_id}")
            root = f"{range_label} {org_name}"

            pm = r.payment_method.value if hasattr(r.payment_method, "value") else str(r.payment_method)

            provider_name = r.provider.display_name if r.provider else ""
            # Unmatched receipts go into a "Diverse" folder and keep a
            # context-rich filename derived from the original upload name
            # (so the user can recognize the file at a glance).
            if provider_name:
                provider_seg = _safe_seg(provider_name)
            else:
                provider_seg = "Diverse"

            # Build the structured filename. For matched receipts we use the
            # provider name; for unmatched ones we use the original filename
            # stem (without extension) — that's what the user remembers.
            d = r.document_date or r.received_at or r.created_at
            date_part = d.strftime("%Y-%m-%d") if d else "unknown-date"
            amount_part = f"{float(r.amount):.2f}-{(r.currency or 'CHF')}" if r.amount is not None else "no-amount"
            ext = os.path.splitext(r.filename)[1] or ".pdf"
            if provider_name:
                name_token = _safe_seg(provider_name)
            else:
                # Strip any prior "{date}_…" prefix we may have added in earlier
                # exports so we don't double-stamp the date.
                stem = os.path.splitext(r.filename)[0]
                stem = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", stem)
                stem = re.sub(r"_[\d.]+-[A-Z]{3}$", "", stem)
                name_token = _safe_seg(stem, "Diverse")
            new_name = f"{date_part}_{name_token}_{amount_part}{ext}"

            # Document type routes to a different top-level folder:
            #   document  → Dokumente/   (non-invoice files: packing slips etc.)
            #   upcoming  → Vorabrechnungen/  (future-dated invoices)
            #   receipt   → normal payment-method folders
            doc_type = (r.document_type.value if hasattr(r.document_type, "value") else str(r.document_type or "receipt"))
            if doc_type == "document":
                arcname = f"{root}/Dokumente/{new_name}"
            elif doc_type == "upcoming":
                arcname = f"{root}/Vorabrechnungen/{provider_seg}/{new_name}"
            elif pm == "credit_card":
                arcname = f"{root}/Kreditkarte/{provider_seg}/{new_name}"
            else:
                folder_de = {
                    "bank_transfer": "Banküberweisung",
                    "twint": "Twint",
                    "cash": "Bargeld",
                    "paypal": "PayPal",
                }.get(pm, "Sonstige")
                arcname = f"{root}/{folder_de}/{new_name}"

            # Deduplicate within zip (rare but possible)
            base = arcname
            i = 1
            try:
                _ = zf.getinfo(arcname)
                while True:
                    stem, _ext = os.path.splitext(base)
                    arcname = f"{stem} ({i}){_ext}"
                    try:
                        _ = zf.getinfo(arcname)
                        i += 1
                    except KeyError:
                        break
            except KeyError:
                pass
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
    engine: str = Body("auto", embed=True),
):
    if engine not in ("api", "local", "auto"):
        raise HTTPException(400, "engine must be one of: api, local, auto")
    rows = (await db.scalars(select(Receipt).where(Receipt.id.in_(ids)))).all()
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    n = 0
    for r in rows:
        if r.email_message_id:
            await pool.enqueue_job("process_message", r.email_message_id, force=True)
        else:
            await pool.enqueue_job("process_uploaded_receipt", r.id, engine)
        n += 1
    return {"ok": True, "count": n, "engine": engine}


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


@router.post("/bulk/re-extract")
async def bulk_re_extract(
    _: Annotated[User, Depends(get_current_user)],
    ids: list[int] = Body(..., embed=True),
):
    """Force re-extraction (Claude PDF/Vision) on a set of receipts."""
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    for rid in ids:
        await pool.enqueue_job("process_uploaded_receipt", rid)
    return {"ok": True, "enqueued": len(ids)}


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
        "ID", "Date of issue", "Due date", "Organization", "Provider", "Brand", "Client",
        "Amount", "Currency", "VAT rate", "VAT amount",
        "Payment method", "Invoice number", "Filename",
        "Status", "Booked", "Booked at", "Bookkeeping ref", "Notes",
    ])
    for r in rows:
        w.writerow([
            r.id,
            (r.document_date.date().isoformat() if r.document_date else ""),
            (r.due_date.date().isoformat() if r.due_date else ""),
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
