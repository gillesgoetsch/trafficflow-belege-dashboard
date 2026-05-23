"""The core processing pipelines invoked by ARQ.

All functions are top-level async fns with signature `(ctx, *args)` — ARQ's
convention. They are idempotent: re-running them on the same input is safe.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.encryption import decrypt_json, decrypt_str
from app.core.logging import get_logger
from app.db.models import (
    ClassificationLayer,
    Connector,
    EmailMessage,
    EmailMessageStatus,
    Mailbox,
    Organization,
    Provider,
    Receipt,
    ReceiptStatus,
    SyncStatus,
    SyncTarget,
)
from app.db.session import SessionLocal
from app.services.classifier import (
    CONFIDENCE_THRESHOLD,
    ClassificationInput,
    classify,
    resolve_provider_from_slug,
)
from app.services.connectors import get_connector_class
from app.services.connectors.base import ReceiptToUpload
from app.services.filename import build_filename
from app.services.imap_fetcher import (
    extract_html_text,
    extract_image_attachments,
    extract_pdf_attachments,
    fetch_new_messages,
    load_email_from_path,
)
from app.services.metadata_extract import extract as extract_meta
from app.services.multi_account import ResolveInput, resolve_client
from app.services.ocr import (
    is_likely_scanned,
    native_text,
    ocr_image_bytes,
    ocr_pdf,
)
from app.services.pdf_renderer import html_to_pdf

logger = get_logger(__name__)


# --- Cron jobs --------------------------------------------------------------


async def poll_all_mailboxes(ctx):
    """Every minute: enqueue sync for any mailbox whose interval has elapsed."""
    redis = ctx["redis"]
    async with SessionLocal() as db:
        mbs = (await db.scalars(select(Mailbox).where(Mailbox.enabled.is_(True)))).all()
        for mb in mbs:
            if mb.last_sync_at is None:
                due = True
            else:
                last = mb.last_sync_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                due = (datetime.now(UTC) - last) >= timedelta(minutes=mb.batch_interval_minutes)
            if due:
                await redis.enqueue_job("sync_mailbox", mb.id, _job_id=f"sync_mailbox:{mb.id}")
    return len(mbs)


async def retry_failed_syncs(ctx):
    """Re-enqueue failed sync_targets with exponential backoff."""
    redis = ctx["redis"]
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        rows = (await db.scalars(
            select(SyncTarget).where(
                SyncTarget.status == SyncStatus.failed,
                SyncTarget.retry_count < 6,
                (SyncTarget.next_retry_at.is_(None)) | (SyncTarget.next_retry_at <= now),
            ).limit(100)
        )).all()
        count = 0
        for t in rows:
            await redis.enqueue_job(
                "sync_receipt_to_connector",
                t.receipt_id, t.connector_id,
                _job_id=f"sync:{t.receipt_id}:{t.connector_id}:r{t.retry_count}",
            )
            count += 1
    return count


# --- IMAP sync --------------------------------------------------------------


async def sync_mailbox(ctx, mailbox_id: int):
    redis = ctx["redis"]
    async with SessionLocal() as db:
        mb = await db.get(Mailbox, mailbox_id)
        if not mb or not mb.enabled:
            return {"ok": False, "reason": "missing_or_disabled"}

        raw_dir = settings.storage_path / "raw-emails" / f"mb-{mb.id}"
        try:
            msgs = await fetch_new_messages(
                host=mb.imap_host, port=mb.imap_port,
                user=mb.imap_user, password=decrypt_str(mb.imap_password_enc),
                use_tls=mb.use_tls, folder=mb.folder,
                last_uid=mb.last_uid, raw_dir=raw_dir,
            )
        except Exception as e:  # noqa: BLE001
            # Tenacity wraps the real cause; unwrap so the UI sees something
            # human ("Login failed") instead of "RetryError[<Future ...>]".
            real = e
            if hasattr(real, "last_attempt") and real.last_attempt is not None:
                try:
                    real.last_attempt.result()
                except Exception as inner:  # noqa: BLE001
                    real = inner
            msg = str(real) or type(real).__name__
            mb.last_error = msg[:1000]
            await db.commit()
            logger.error("sync_mailbox.fetch_failed", mailbox_id=mb.id, error=msg)
            return {"ok": False, "error": msg}

        enqueued = 0
        max_uid = mb.last_uid
        for m in msgs:
            try:
                em = EmailMessage(
                    mailbox_id=mb.id,
                    organization_id=mb.organization_id,
                    message_id=m.message_id,
                    imap_uid=m.uid,
                    received_at=m.received_at,
                    subject=m.subject,
                    sender_name=m.sender_name,
                    sender_email=m.sender_email,
                    to_address=m.to_address,
                    raw_size=m.raw_size,
                    raw_path=m.raw_path,
                )
                db.add(em)
                await db.flush()
                await redis.enqueue_job("process_message", em.id, _job_id=f"process:{em.id}")
                enqueued += 1
            except IntegrityError:
                await db.rollback()  # duplicate message_id — skip
            max_uid = max(max_uid, m.uid)

        mb.last_uid = max_uid
        mb.last_sync_at = datetime.now(UTC)
        mb.last_error = None
        await db.commit()
        logger.info("sync_mailbox.done", mailbox_id=mb.id, enqueued=enqueued, last_uid=max_uid)
        return {"ok": True, "enqueued": enqueued, "last_uid": max_uid}


# --- Per-message processing -------------------------------------------------


async def process_message(ctx, email_message_id: int, force: bool = False):
    redis = ctx["redis"]
    async with SessionLocal() as db:
        em: EmailMessage | None = await db.get(EmailMessage, email_message_id)
        if not em:
            return {"ok": False, "reason": "no_email"}

        if em.status == EmailMessageStatus.finished and not force:
            return {"ok": True, "skipped": True}

        mb = await db.get(Mailbox, em.mailbox_id)
        if not mb or not em.raw_path or not os.path.exists(em.raw_path):
            em.status = EmailMessageStatus.failed
            await db.commit()
            return {"ok": False, "reason": "missing_raw"}

        msg = load_email_from_path(em.raw_path)
        html, plain = extract_html_text(msg)
        body_text = (plain or "")[:4000]
        if not body_text and html:
            # crude fallback so the LLM can read it
            from bs4 import BeautifulSoup
            body_text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)[:4000]

        inp = ClassificationInput(
            sender_email=em.sender_email,
            sender_name=em.sender_name,
            subject=em.subject,
            body_text=body_text,
            organization_id=em.organization_id,
        )
        result = await classify(db, inp)

        log_entry = {
            "ts": datetime.utcnow().isoformat(),
            "event": "classified",
            "layer": result.layer,
            "is_receipt": result.is_receipt,
            "provider_id": result.provider_id,
            "provider_slug": result.provider_slug,
            "confidence": result.confidence,
            "rule_id": result.rule_id,
            "notes": result.notes,
        }

        # Confidently not a receipt → archive the email & exit
        if not result.is_receipt and result.confidence >= 0.8 and result.layer == "2":
            em.status = EmailMessageStatus.not_a_receipt
            await db.commit()
            return {"ok": True, "result": "not_a_receipt"}

        # If layer 3 or no provider → emit a placeholder receipt for review queue
        provider_id = result.provider_id
        review_needed = (result.layer == "3") or (not provider_id) or (result.confidence < CONFIDENCE_THRESHOLD)

        # --- Materialize the PDF ----------------------------------------------
        org: Organization = await db.get(Organization, em.organization_id)
        provider: Provider | None = await db.get(Provider, provider_id) if provider_id else None
        prov_name = provider.display_name if provider else (result.provider_slug or "Unknown")

        pdf_attachments = extract_pdf_attachments(msg)
        image_attachments = extract_image_attachments(msg)

        chosen_pdf_bytes: bytes | None = None
        chosen_source = "html_render"
        ocr_data = None

        if pdf_attachments:
            # Use the first PDF; if scanned, run OCR for metadata
            name, data = pdf_attachments[0]
            chosen_pdf_bytes = data
            chosen_source = "attachment_pdf"
            log_entry.setdefault("attachments", []).append(name)
        elif image_attachments:
            # OCR + render as PDF
            name, img_bytes, ctype = image_attachments[0]
            ocr_data = await ocr_image_bytes(img_bytes, media_type=ctype)
            chosen_source = "ocr_image"
            # Render the image into a PDF page
            from io import BytesIO
            from PIL import Image
            try:
                img = Image.open(BytesIO(img_bytes)).convert("RGB")
                buf = BytesIO()
                img.save(buf, format="PDF")
                chosen_pdf_bytes = buf.getvalue()
            except Exception:
                # Fall back to HTML render
                chosen_pdf_bytes = None
        # If still no PDF: render the HTML body
        if not chosen_pdf_bytes:
            html_to_render = html or f"<pre>{(plain or '').replace('<', '&lt;')}</pre>"
            tmp_path = settings.storage_path / "tmp" / f"em-{em.id}.pdf"
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            await html_to_pdf(html_to_render, tmp_path, title=em.subject or prov_name)
            chosen_pdf_bytes = tmp_path.read_bytes()
            try:
                tmp_path.unlink()
            except OSError:
                pass
            chosen_source = "html_render"

        # OCR (if scanned PDF) or native text + regex metadata
        meta_text = ""
        if chosen_source == "attachment_pdf":
            tmp_path = settings.storage_path / "tmp" / f"em-{em.id}-att.pdf"
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(chosen_pdf_bytes)
            if is_likely_scanned(tmp_path):
                try:
                    ocr_data = await ocr_pdf(tmp_path)
                    meta_text = ocr_data.text
                except Exception as e:  # noqa: BLE001
                    logger.warning("ocr_pdf.failed", error=str(e))
            else:
                meta_text = native_text(tmp_path)
            try:
                tmp_path.unlink()
            except OSError:
                pass
        elif chosen_source == "ocr_image" and ocr_data:
            meta_text = ocr_data.text
        else:
            meta_text = body_text

        meta = extract_meta(meta_text)

        # If OCR gave us cleaner metadata, prefer it
        if ocr_data and ocr_data.is_receipt:
            if ocr_data.date:
                try:
                    from dateutil import parser as _dp
                    meta.date = _dp.parse(ocr_data.date)
                except Exception:
                    pass
            if ocr_data.amount:
                try:
                    from decimal import Decimal
                    meta.amount = Decimal(str(ocr_data.amount).replace(",", "."))
                except Exception:
                    pass
            if ocr_data.currency:
                meta.currency = ocr_data.currency
            if ocr_data.invoice_number:
                meta.invoice_number = ocr_data.invoice_number
            if ocr_data.language:
                meta.language = ocr_data.language
            if not provider and ocr_data.provider_slug:
                provider = await resolve_provider_from_slug(db, ocr_data.provider_slug)
                if provider:
                    provider_id = provider.id
                    prov_name = provider.display_name

        # Resolve sub-client
        sub_client = await resolve_client(db, ResolveInput(
            organization_id=em.organization_id,
            provider_id=provider_id,
            to_address=em.to_address,
            sender_email=em.sender_email,
            subject=em.subject,
            body_text=meta_text or body_text,
        ))

        # Determine final fields
        currency = meta.currency or (org.default_currency if org else "CHF")
        doc_date = meta.date or em.received_at or datetime.now(UTC)

        filename = build_filename(
            template=(org.filename_template if org else "{date}_{provider}_{client}_{amount}-{currency}"),
            date=doc_date, provider=prov_name,
            client=(sub_client.name if sub_client else None),
            amount=meta.amount, currency=currency, invoice_number=meta.invoice_number,
        )

        out_dir = settings.storage_path / f"org-{em.organization_id}" / f"{doc_date.year}" / f"{doc_date.month:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(chosen_pdf_bytes).hexdigest()
        out_path = out_dir / filename
        out_path.write_bytes(chosen_pdf_bytes)

        # Persist Receipt — idempotent reprocess updates existing row.
        existing = (await db.scalars(
            select(Receipt).where(Receipt.email_message_id == em.id)
        )).first()

        layer_enum_map = {"1": ClassificationLayer.layer1, "2": ClassificationLayer.layer2, "3": ClassificationLayer.layer3}
        new_layer = layer_enum_map.get(result.layer, ClassificationLayer.layer3)

        if existing:
            existing.provider_id = provider_id
            existing.client_id = sub_client.id if sub_client else None
            existing.document_date = doc_date
            existing.received_at = em.received_at
            existing.amount = meta.amount
            existing.currency = currency
            existing.invoice_number = meta.invoice_number
            existing.language = meta.language
            existing.filename = filename
            existing.file_path = str(out_path)
            existing.file_size = len(chosen_pdf_bytes)
            existing.file_sha256 = digest
            existing.classification_layer = new_layer if not review_needed else ClassificationLayer.layer3
            existing.confidence = result.confidence
            existing.status = ReceiptStatus.review_needed if review_needed else ReceiptStatus.processed
            existing.review_reason = result.notes if review_needed else None
            existing.raw_metadata = {**(existing.raw_metadata or {}), "source": chosen_source, "ocr": bool(ocr_data)}
            existing.processing_log = (existing.processing_log or []) + [log_entry]
            receipt = existing
        else:
            receipt = Receipt(
                organization_id=em.organization_id,
                mailbox_id=em.mailbox_id,
                email_message_id=em.id,
                provider_id=provider_id,
                client_id=sub_client.id if sub_client else None,
                document_date=doc_date,
                received_at=em.received_at,
                amount=meta.amount,
                currency=currency,
                invoice_number=meta.invoice_number,
                language=meta.language,
                filename=filename,
                file_path=str(out_path),
                file_size=len(chosen_pdf_bytes),
                file_sha256=digest,
                source="email",
                classification_layer=new_layer if not review_needed else ClassificationLayer.layer3,
                confidence=result.confidence,
                status=ReceiptStatus.review_needed if review_needed else ReceiptStatus.processed,
                review_reason=result.notes if review_needed else None,
                raw_metadata={"source": chosen_source, "ocr": bool(ocr_data)},
                processing_log=[log_entry],
            )
            db.add(receipt)

        em.status = EmailMessageStatus.review_needed if review_needed else EmailMessageStatus.finished
        await db.commit()
        await db.refresh(receipt)

        # Enqueue connector syncs for processed receipts
        if not review_needed:
            connectors = (await db.scalars(
                select(Connector).where(
                    Connector.organization_id == em.organization_id,
                    Connector.enabled.is_(True),
                )
            )).all()
            for c in connectors:
                await redis.enqueue_job(
                    "sync_receipt_to_connector", receipt.id, c.id,
                    _job_id=f"sync:{receipt.id}:{c.id}",
                )

        return {"ok": True, "receipt_id": receipt.id, "review": review_needed}


# --- Manual upload processing ----------------------------------------------


async def process_uploaded_receipt(ctx, receipt_id: int):
    """Extract metadata using Claude (native PDF reading or Vision) and update
    the receipt. Also runs org-routing — if the content matches a routing rule,
    reassigns the receipt to that org."""
    from app.services.claude_extract import extract_path
    from app.services.org_routing import RoutingInput, route

    async with SessionLocal() as db:
        r = await db.get(Receipt, receipt_id)
        if not r:
            return {"ok": False, "reason": "missing"}
        path = Path(r.file_path)
        if not path.exists():
            return {"ok": False, "reason": "file_missing"}

        try:
            ext = await extract_path(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("upload.claude_extract.failed", receipt_id=r.id, error=str(e))
            ext = None

        log_entry = {
            "ts": datetime.utcnow().isoformat(),
            "event": "claude_extracted",
            "is_receipt": getattr(ext, "is_receipt", None),
            "vendor": getattr(ext, "vendor", None),
            "amount": str(getattr(ext, "total_amount", "") or ""),
            "currency": getattr(ext, "currency", None),
            "customer_hint": getattr(ext, "customer_hint", None),
        }

        if ext and ext.is_receipt:
            from dateutil import parser as _dp
            if ext.document_date:
                try:
                    r.document_date = _dp.parse(ext.document_date)
                except Exception:
                    pass
            if ext.total_amount is not None:
                r.amount = ext.total_amount
            if ext.currency:
                r.currency = ext.currency
            if ext.vat_rate is not None:
                r.vat_rate = ext.vat_rate
            if ext.vat_amount is not None:
                r.vat_amount = ext.vat_amount
            if ext.invoice_number:
                r.invoice_number = ext.invoice_number
            if ext.language:
                r.language = ext.language
            if ext.notes and not r.notes:
                r.notes = ext.notes
            if not r.provider_id and ext.vendor_slug:
                prov = await resolve_provider_from_slug(db, ext.vendor_slug)
                if prov:
                    r.provider_id = prov.id

            # Org routing — re-route to the right org if the doc content says so
            new_org = await route(db, RoutingInput(
                sender_email=None, subject=None, body_text=None,
                customer_hint=ext.customer_hint or "",
                default_organization_id=r.organization_id,
            ))
            if new_org and new_org != r.organization_id:
                log_entry["routed_from_org"] = r.organization_id
                log_entry["routed_to_org"] = new_org
                r.organization_id = new_org

            r.status = ReceiptStatus.processed if r.provider_id else ReceiptStatus.review_needed
        elif ext and ext.is_receipt is False:
            # Confidently not a receipt
            r.review_reason = "Claude: not_a_receipt"

        log = list(r.processing_log or [])
        log.append(log_entry)
        r.processing_log = log
        await db.commit()
        return {"ok": True, "amount": str(r.amount) if r.amount else None}


def _image_media(path: Path) -> str:
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/jpeg")


# --- Connector syncs --------------------------------------------------------


async def sync_receipt_to_connector(ctx, receipt_id: int, connector_id: int):
    async with SessionLocal() as db:
        r = await db.get(Receipt, receipt_id)
        c = await db.get(Connector, connector_id)
        if not r or not c or not c.enabled:
            return {"ok": False}

        cls = get_connector_class(c.type.value)
        cfg = decrypt_json(c.config_enc) or {}
        instance = cls(cfg)
        prov = await db.get(Provider, r.provider_id) if r.provider_id else None
        client = None
        if r.client_id:
            from app.db.models import Client
            client = await db.get(Client, r.client_id)
        upload = ReceiptToUpload(
            receipt_id=r.id, organization_id=r.organization_id,
            file_path=Path(r.file_path), filename=r.filename,
            document_date=r.document_date or r.received_at,
            provider=(prov.display_name if prov else None),
            client=(client.name if client else None),
            amount=r.amount, currency=r.currency,
        )
        try:
            result = await instance.upload(upload)
        except Exception as e:  # noqa: BLE001
            result = type("R", (), {"ok": False, "external_id": None, "error": str(e)})()

        st = (await db.scalars(select(SyncTarget).where(
            SyncTarget.receipt_id == r.id, SyncTarget.connector_id == c.id,
        ))).first()
        if not st:
            st = SyncTarget(receipt_id=r.id, connector_id=c.id)
            db.add(st)

        if result.ok:
            st.status = SyncStatus.synced
            st.synced_at = datetime.now(UTC)
            st.external_id = result.external_id
            st.error = None
        else:
            st.status = SyncStatus.failed
            st.error = (result.error or "unknown")[:1000]
            st.retry_count = (st.retry_count or 0) + 1
            # exponential backoff: 2^n minutes, capped at 4h
            backoff = min(2 ** st.retry_count, 240)
            st.next_retry_at = datetime.now(UTC) + timedelta(minutes=backoff)
        await db.commit()
        return {"ok": result.ok, "external_id": result.external_id}


async def sync_receipt_all_connectors(ctx, receipt_id: int):
    async with SessionLocal() as db:
        r = await db.get(Receipt, receipt_id)
        if not r:
            return {"ok": False}
        connectors = (await db.scalars(
            select(Connector).where(
                Connector.organization_id == r.organization_id,
                Connector.enabled.is_(True),
            )
        )).all()
    redis = ctx["redis"]
    for c in connectors:
        await redis.enqueue_job("sync_receipt_to_connector", receipt_id, c.id)
    return {"ok": True, "fanout": len(connectors)}
