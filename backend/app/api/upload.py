"""Drag-and-drop manual receipt upload."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Annotated

from arq.connections import create_pool, RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import settings
from app.core.security import get_current_user
from app.db.models import (
    ClassificationLayer,
    Organization,
    PaymentMethod,
    Receipt,
    ReceiptStatus,
    User,
)
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

ALLOWED = {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp", "image/heic"}


def _ext_from(filename: str | None, content_type: str | None) -> str:
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext:
            return ext
    return {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/heic": ".heic",
    }.get(content_type or "", ".bin")


async def _persist_upload(
    db: AsyncSession,
    *,
    organization_id: int,
    file: UploadFile,
    provider_id: int | None = None,
    client_id: int | None = None,
    payment_method: PaymentMethod = PaymentMethod.unknown,
    brand: str | None = None,
    document_date: datetime | None = None,
    amount: float | None = None,
    currency: str | None = None,
    enqueue_ocr: bool = True,
    skip_duplicate: bool = True,
) -> dict:
    if file.content_type not in ALLOWED:
        raise HTTPException(415, f"Unsupported file type: {file.content_type}")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "File too large")

    org = await db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    digest = hashlib.sha256(content).hexdigest()
    if skip_duplicate:
        from sqlalchemy import select
        existing = await db.scalar(
            select(Receipt).where(
                Receipt.organization_id == organization_id,
                Receipt.file_sha256 == digest,
            )
        )
        if existing:
            return {"ok": True, "receipt_id": existing.id, "status": existing.status.value, "duplicate": True}

    now = datetime.utcnow()
    doc_dt = document_date or now
    base = settings.storage_path / f"org-{organization_id}" / f"{doc_dt.year}" / f"{doc_dt.month:02d}"
    base.mkdir(parents=True, exist_ok=True)
    ext = _ext_from(file.filename, file.content_type)
    target = base / f"upload-{digest[:12]}{ext}"
    target.write_bytes(content)

    is_pdf = ext == ".pdf"
    needs_review = not provider_id  # if no provider mapped, send to review queue
    status = ReceiptStatus.processed if (provider_id and not needs_review) else ReceiptStatus.review_needed

    r = Receipt(
        organization_id=organization_id,
        provider_id=provider_id,
        client_id=client_id,
        document_date=doc_dt,
        received_at=now,
        amount=amount,
        currency=(currency or org.default_currency),
        filename=target.name,
        file_path=str(target),
        file_size=len(content),
        file_sha256=digest,
        source="upload",
        classification_layer=ClassificationLayer.manual,
        confidence=1.0,
        status=status,
        payment_method=payment_method,
        brand=brand,
        raw_metadata={
            "upload_filename": file.filename,
            "content_type": file.content_type,
        },
        processing_log=[{"ts": now.isoformat(), "event": "upload", "source": "manual"}],
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)

    # Trigger OCR/extraction if we don't already have amount + provider
    if enqueue_ocr and (not is_pdf or amount is None or not provider_id):
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("process_uploaded_receipt", r.id)

    return {"ok": True, "receipt_id": r.id, "status": r.status.value, "duplicate": False}


@router.post("")
async def upload_receipt(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[int, Form(...)],
    file: Annotated[UploadFile, File(...)],
    provider_id: Annotated[int | None, Form()] = None,
    client_id: Annotated[int | None, Form()] = None,
    payment_method: Annotated[PaymentMethod, Form()] = PaymentMethod.unknown,
    brand: Annotated[str | None, Form()] = None,
):
    return await _persist_upload(
        db,
        organization_id=organization_id,
        file=file,
        provider_id=provider_id,
        client_id=client_id,
        payment_method=payment_method,
        brand=brand,
    )


@router.post("/bulk")
async def upload_bulk(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[int, Form(...)],
    files: Annotated[list[UploadFile], File(...)],
    provider_id: Annotated[int | None, Form()] = None,
    payment_method: Annotated[PaymentMethod, Form()] = PaymentMethod.unknown,
    brand: Annotated[str | None, Form()] = None,
):
    """Upload many receipts at once. All share the same provider / payment_method / brand."""
    results = []
    for file in files:
        try:
            r = await _persist_upload(
                db,
                organization_id=organization_id,
                file=file,
                provider_id=provider_id,
                payment_method=payment_method,
                brand=brand,
            )
            results.append({"filename": file.filename, **r})
        except HTTPException as e:
            results.append({"filename": file.filename, "ok": False, "error": e.detail})
        except Exception as e:  # noqa: BLE001
            results.append({"filename": file.filename, "ok": False, "error": str(e)})
    return {"results": results, "count": len(results)}
