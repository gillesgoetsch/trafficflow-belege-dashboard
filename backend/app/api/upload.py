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
from app.db.models import Organization, Receipt, ReceiptStatus, User, ClassificationLayer
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

ALLOWED = {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp", "image/heic"}


@router.post("")
async def upload_receipt(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[int, Form(...)],
    file: Annotated[UploadFile, File(...)],
    provider_id: Annotated[int | None, Form()] = None,
    client_id: Annotated[int | None, Form()] = None,
):
    if file.content_type not in ALLOWED:
        raise HTTPException(415, f"Unsupported file type: {file.content_type}")
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "File too large")

    org = await db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    digest = hashlib.sha256(content).hexdigest()
    now = datetime.utcnow()
    base = settings.storage_path / f"org-{organization_id}" / f"{now.year}" / f"{now.month:02d}"
    base.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(file.filename or "upload")[1].lower() or ".pdf"
    target = base / f"upload-{digest[:12]}{ext}"
    target.write_bytes(content)

    r = Receipt(
        organization_id=organization_id,
        provider_id=provider_id,
        client_id=client_id,
        document_date=now,
        received_at=now,
        currency=org.default_currency,
        filename=target.name,
        file_path=str(target),
        file_size=len(content),
        file_sha256=digest,
        source="upload",
        classification_layer=ClassificationLayer.manual,
        confidence=1.0,
        status=ReceiptStatus.processed if (provider_id and ext == ".pdf") else ReceiptStatus.review_needed,
        raw_metadata={"upload_filename": file.filename, "content_type": file.content_type},
        processing_log=[{"ts": now.isoformat(), "event": "upload", "source": "manual"}],
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)

    # If it's not a PDF, enqueue OCR + classification on this receipt
    if ext != ".pdf" or not provider_id:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("process_uploaded_receipt", r.id)

    return {"ok": True, "receipt_id": r.id, "status": r.status.value}
