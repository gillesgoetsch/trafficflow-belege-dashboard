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
    BrandRoute,
    ClassificationLayer,
    Connector,
    ConnectorMode,
    EmailMessage,
    EmailMessageStatus,
    EmailSkipRule,
    Mailbox,
    MatchType,
    Organization,
    Provider,
    ProviderAccountMapping,
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
from app.services.connectors.base import ReceiptToUpload, SyncResult
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


# --- Skip rules + brand routing helpers -------------------------------------


def _match_haystack(mt: MatchType, sender_email: str, sender_domain: str,
                    subject: str, body: str, to_address: str) -> str:
    if mt == MatchType.sender_domain:
        return sender_domain
    if mt == MatchType.sender_email:
        return sender_email
    if mt == MatchType.sender_contains:
        return sender_email
    if mt == MatchType.subject_contains:
        return subject
    if mt == MatchType.body_contains:
        return body
    if mt == MatchType.plus_alias:
        return to_address
    return ""


def _rule_hits(mt: MatchType, value: str, haystack: str) -> bool:
    v = (value or "").lower().strip()
    h = (haystack or "").lower()
    if not v:
        return False
    if mt == MatchType.sender_domain:
        return h.endswith(v)
    if mt == MatchType.sender_email:
        return h == v
    return v in h


async def find_skip_rule(
    db, organization_id: int, sender_email: str | None, subject: str | None,
    body_text: str | None, to_address: str | None,
) -> "EmailSkipRule | None":
    """Return the highest-priority skip rule that matches this email."""
    rules = (await db.scalars(
        select(EmailSkipRule)
        .where((EmailSkipRule.organization_id == organization_id) | (EmailSkipRule.organization_id.is_(None)))
        .order_by(EmailSkipRule.priority.desc())
    )).all()
    se = (sender_email or "").lower()
    sd = se.split("@", 1)[-1] if "@" in se else ""
    sub = subject or ""
    bdy = body_text or ""
    to = to_address or ""
    for r in rules:
        hay = _match_haystack(r.match_type, se, sd, sub, bdy, to)
        if _rule_hits(r.match_type, r.match_value, hay):
            return r
    return None


async def find_brand_route(
    db, source_organization_id: int, provider_id: int | None,
    sender_email: str | None, subject: str | None, body_text: str | None,
    to_address: str | None,
) -> "BrandRoute | None":
    """Return the highest-priority brand route that matches."""
    rules = (await db.scalars(
        select(BrandRoute)
        .where(BrandRoute.source_organization_id == source_organization_id)
        .order_by(BrandRoute.priority.desc())
    )).all()
    se = (sender_email or "").lower()
    sd = se.split("@", 1)[-1] if "@" in se else ""
    sub = subject or ""
    bdy = body_text or ""
    to = to_address or ""
    for r in rules:
        if r.provider_id and provider_id and r.provider_id != provider_id:
            continue
        hay = _match_haystack(r.match_type, se, sd, sub, bdy, to)
        if _rule_hits(r.match_type, r.match_value, hay):
            return r
    return None


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


async def requeue_stuck_emails(ctx):
    """Catch email_messages that were fetched but never processed.

    Happens when the worker container is killed (e.g. during a deploy)
    after sync_mailbox inserted the email row but before process_message
    finished — the queued job can be lost. This cron picks up any email
    stuck at 'pending' for more than 5 minutes and re-enqueues.
    """
    redis = ctx["redis"]
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    async with SessionLocal() as db:
        rows = (await db.scalars(
            select(EmailMessage).where(
                EmailMessage.status == EmailMessageStatus.pending,
                EmailMessage.created_at < cutoff,
            ).limit(50)
        )).all()
        count = 0
        for em in rows:
            # Use a unique job_id per attempt so the queue doesn't dedupe
            # against an old failed entry.
            attempt = int(datetime.now(UTC).timestamp())
            await redis.enqueue_job(
                "process_message", em.id,
                _job_id=f"process:{em.id}:retry{attempt}",
            )
            count += 1
        if count:
            logger.info("requeue_stuck_emails.done", count=count)
    return count


# --- Inbound cloud folders --------------------------------------------------


async def poll_all_inbound_folders(ctx):
    """Every minute: enqueue scan for any inbound folder whose interval has elapsed."""
    from app.db.models import InboundFolder

    redis = ctx["redis"]
    async with SessionLocal() as db:
        folders = (await db.scalars(
            select(InboundFolder).where(InboundFolder.enabled.is_(True))
        )).all()
        for fd in folders:
            if fd.last_poll_at is None:
                due = True
            else:
                last = fd.last_poll_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                due = (datetime.now(UTC) - last) >= timedelta(minutes=fd.batch_interval_minutes)
            if due:
                await redis.enqueue_job(
                    "scan_inbound_folder", fd.id,
                    _job_id=f"scan_inbound:{fd.id}",
                )
    return len(folders)


async def scan_inbound_folder(ctx, folder_id: int):
    """List remote files, dedup against inbound_files, enqueue ingestion for new ones."""
    import hashlib as _hl

    from app.core.encryption import decrypt_json
    from app.db.models import InboundFile, InboundFileStatus, InboundFolder
    from app.services.inbound import build_connector

    redis = ctx["redis"]
    async with SessionLocal() as db:
        fd: InboundFolder | None = await db.get(InboundFolder, folder_id)
        if not fd or not fd.enabled:
            return {"ok": False, "reason": "missing_or_disabled"}

        config = {}
        if fd.config_enc:
            try:
                config = decrypt_json(fd.config_enc) or {}
            except Exception:  # noqa: BLE001
                config = {}

        try:
            conn = build_connector(fd.type, fd.share_url, config)
            remote_files = await conn.list_files()
        except Exception as e:  # noqa: BLE001
            fd.last_error = str(e)[:1000]
            fd.last_poll_at = datetime.now(UTC)
            await db.commit()
            logger.error("scan_inbound.failed", folder_id=fd.id, error=str(e))
            return {"ok": False, "error": str(e)}

        # Diff against known files
        known = {
            (r.remote_id): r for r in (await db.scalars(
                select(InboundFile).where(InboundFile.folder_id == fd.id)
            )).all()
        }
        new_count = 0
        for rf in remote_files:
            if rf.remote_id in known:
                continue
            rec = InboundFile(
                folder_id=fd.id,
                remote_id=rf.remote_id,
                filename=rf.filename,
                size=rf.size,
                remote_mtime=rf.mtime,
                status=InboundFileStatus.pending,
            )
            db.add(rec)
            await db.flush()
            await redis.enqueue_job(
                "process_inbound_file", rec.id,
                _job_id=f"process_inbound:{rec.id}",
            )
            new_count += 1

        fd.last_poll_at = datetime.now(UTC)
        fd.last_error = None
        await db.commit()
        logger.info("scan_inbound.done", folder_id=fd.id, new_files=new_count, total=len(remote_files))
        return {"ok": True, "new_files": new_count, "total": len(remote_files)}


async def process_inbound_file(ctx, inbound_file_id: int):
    """Download a remote file and run it through the receipt pipeline.

    Reuses the same metadata extraction / OCR / classification logic as the
    email path, but the source is 'cloud_folder'. When no receipt indicators
    are found, the document is stored with document_type='document' instead
    of being forced into a 0-amount receipt.
    """
    import hashlib as _hl

    from app.core.encryption import decrypt_json
    from app.db.models import (
        DocumentType,
        InboundFile,
        InboundFileStatus,
        InboundFolder,
    )
    from app.services.inbound import build_connector

    async with SessionLocal() as db:
        rec: InboundFile | None = await db.get(InboundFile, inbound_file_id)
        if not rec:
            return {"ok": False, "reason": "no_file"}
        fd = await db.get(InboundFolder, rec.folder_id)
        if not fd:
            rec.status = InboundFileStatus.failed
            rec.error = "missing_folder"
            await db.commit()
            return {"ok": False}

        rec.status = InboundFileStatus.processing
        await db.commit()

        try:
            config = decrypt_json(fd.config_enc) if fd.config_enc else {}
        except Exception:  # noqa: BLE001
            config = {}

        try:
            conn = build_connector(fd.type, fd.share_url, config or {})
            data = await conn.download_file(rec.remote_id)
        except Exception as e:  # noqa: BLE001
            rec.status = InboundFileStatus.failed
            rec.error = str(e)[:1000]
            await db.commit()
            logger.error("process_inbound.download_failed", file_id=rec.id, error=str(e))
            return {"ok": False, "error": str(e)}

        sha = _hl.sha256(data).hexdigest()
        # Hash-based dedup across folders + email path
        existing_receipt = (await db.scalars(
            select(Receipt).where(Receipt.file_sha256 == sha)
        )).first()
        if existing_receipt:
            rec.sha256 = sha
            rec.status = InboundFileStatus.processed
            rec.receipt_id = existing_receipt.id
            rec.processed_at = datetime.now(UTC)
            await db.commit()
            return {"ok": True, "deduped": True, "receipt_id": existing_receipt.id}
        rec.sha256 = sha

        # Determine document_date — prefer extraction, fall back to remote mtime
        org = await db.get(Organization, fd.organization_id)
        doc_date = rec.remote_mtime or datetime.now(UTC)

        # Write the raw bytes to a stable location so the pipeline below can
        # read them with the same code paths the email worker uses.
        tmp_dir = settings.storage_path / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        is_pdf = rec.filename.lower().endswith(".pdf")
        if is_pdf:
            tmp_pdf = tmp_dir / f"inbound-{rec.id}.pdf"
            tmp_pdf.write_bytes(data)
            pdf_bytes = data
        else:
            # Image — convert to PDF
            from io import BytesIO
            from PIL import Image
            try:
                img = Image.open(BytesIO(data)).convert("RGB")
                buf = BytesIO()
                img.save(buf, format="PDF")
                pdf_bytes = buf.getvalue()
            except Exception as e:  # noqa: BLE001
                rec.status = InboundFileStatus.failed
                rec.error = f"image_decode: {e}"
                await db.commit()
                return {"ok": False, "error": str(e)}
            tmp_pdf = tmp_dir / f"inbound-{rec.id}.pdf"
            tmp_pdf.write_bytes(pdf_bytes)

        # Extract text (native or OCR) + metadata
        from app.services.ocr import is_likely_scanned, native_text, ocr_pdf
        from app.services.metadata_extract import extract as extract_meta

        meta_text = ""
        ocr_data = None
        try:
            if is_pdf and is_likely_scanned(tmp_pdf):
                try:
                    ocr_data = await ocr_pdf(tmp_pdf)
                    meta_text = ocr_data.text
                except Exception as e:  # noqa: BLE001
                    logger.warning("inbound.ocr_failed", file_id=rec.id, error=str(e))
                    meta_text = ""
            else:
                meta_text = native_text(tmp_pdf)
        finally:
            try:
                tmp_pdf.unlink()
            except OSError:
                pass

        meta = extract_meta(meta_text or "")

        # Classification — feed the PDF text as 'body_text', filename as 'subject'.
        # Skip rules + brand routes still apply (they check the same haystacks).
        from app.services.classifier import ClassificationInput, classify
        from app.services.classifier import resolve_provider_from_slug

        inp = ClassificationInput(
            sender_email=None, sender_name=None,
            subject=rec.filename, body_text=meta_text or "",
            organization_id=fd.organization_id,
        )
        cls = await classify(db, inp)
        provider = await db.get(Provider, cls.provider_id) if cls.provider_id else None
        if not provider and ocr_data and getattr(ocr_data, "provider_slug", None):
            provider = await resolve_provider_from_slug(db, ocr_data.provider_slug)
        provider_id = provider.id if provider else None
        prov_name = provider.display_name if provider else (cls.provider_slug or "Unknown")

        # Brand route override (same logic as email path)
        effective_org_id = fd.organization_id
        brand_override = None
        route = await find_brand_route(
            db, fd.organization_id, provider_id,
            None, rec.filename, meta_text or "", None,
        )
        if route:
            effective_org_id = route.target_organization_id
            brand_override = route.brand
            org = await db.get(Organization, effective_org_id)

        # Sub-client resolution
        from app.services.multi_account import ResolveInput, resolve_client
        sub_client = await resolve_client(db, ResolveInput(
            organization_id=effective_org_id,
            provider_id=provider_id,
            to_address=None, sender_email=None,
            subject=rec.filename, body_text=meta_text or "",
        ))

        # OCR amount/date if it filled them in
        if ocr_data:
            if ocr_data.date and not meta.date:
                try:
                    from dateutil import parser as _dp
                    meta.date = _dp.parse(ocr_data.date)
                except Exception:
                    pass
            if ocr_data.amount and not meta.amount:
                try:
                    from decimal import Decimal
                    meta.amount = Decimal(str(ocr_data.amount).replace(",", "."))
                except Exception:
                    pass
            if ocr_data.currency and not meta.currency:
                meta.currency = ocr_data.currency
            if ocr_data.invoice_number and not meta.invoice_number:
                meta.invoice_number = ocr_data.invoice_number

        # Only default to the org currency when an amount was found; otherwise
        # leave it NULL instead of fabricating "CHF".
        currency = meta.currency or (org.default_currency if (meta.amount is not None and org) else None)
        if meta.date:
            doc_date = meta.date

        # Determine document_type: receipt vs archive document
        has_receipt_indicator = bool(meta.amount or meta.invoice_number or (ocr_data and ocr_data.is_receipt))
        document_type = "receipt" if has_receipt_indicator else "document"

        # Build filename + final path
        filename = build_filename(
            template=(org.filename_template if org else "{date}_{provider}_{client}_{amount}-{currency}"),
            date=doc_date, provider=prov_name,
            client=(sub_client.name if sub_client else None),
            amount=meta.amount, currency=currency, invoice_number=meta.invoice_number,
        )
        out_dir = settings.storage_path / f"org-{effective_org_id}" / f"{doc_date.year}" / f"{doc_date.month:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        out_path.write_bytes(pdf_bytes)

        receipt = Receipt(
            organization_id=effective_org_id,
            mailbox_id=None,
            email_message_id=None,
            provider_id=provider_id,
            client_id=sub_client.id if sub_client else None,
            document_date=doc_date,
            received_at=rec.remote_mtime or datetime.now(UTC),
            amount=meta.amount,
            currency=currency,
            invoice_number=meta.invoice_number,
            language=meta.language,
            filename=filename,
            file_path=str(out_path),
            file_size=len(pdf_bytes),
            file_sha256=sha,
            source="cloud_folder",
            classification_layer={
                "1": ClassificationLayer.layer1,
                "2": ClassificationLayer.layer2,
                "3": ClassificationLayer.layer3,
            }.get(cls.layer, ClassificationLayer.layer3),
            confidence=cls.confidence,
            status=ReceiptStatus.processed,  # archive docs go straight to processed
            review_reason=None,
            brand=brand_override,
            document_type=document_type,
            raw_metadata={
                "source": "cloud_folder",
                "inbound_folder_id": fd.id,
                "inbound_file_id": rec.id,
                "remote_id": rec.remote_id,
                "ocr": bool(ocr_data),
            },
            processing_log=[{
                "ts": datetime.utcnow().isoformat(),
                "event": "ingested_from_inbound",
                "folder_id": fd.id,
                "type": fd.type.value if hasattr(fd.type, "value") else str(fd.type),
                "document_type": document_type,
                "layer": cls.layer,
                "confidence": cls.confidence,
            }],
        )
        db.add(receipt)
        await db.flush()

        rec.status = InboundFileStatus.processed
        rec.receipt_id = receipt.id
        rec.processed_at = datetime.now(UTC)
        await db.commit()
        logger.info(
            "process_inbound.done",
            file_id=rec.id, receipt_id=receipt.id,
            document_type=document_type, layer=cls.layer,
        )
        return {"ok": True, "receipt_id": receipt.id, "document_type": document_type}


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

        # --- Pre-classification skip filter -----------------------------------
        # Catches privacy-policy / TOS / newsletter emails from senders that
        # otherwise have a positive Layer 1 rule (Spotify, Meta, etc).
        skip = await find_skip_rule(
            db, em.organization_id,
            em.sender_email, em.subject, body_text, em.to_address,
        )
        if skip:
            em.status = EmailMessageStatus.not_a_receipt
            await db.commit()
            logger.info(
                "process_message.skipped",
                email_message_id=em.id,
                rule_id=skip.id,
                reason=skip.reason or "matched email_skip_rules",
            )
            return {"ok": True, "result": "not_a_receipt", "skip_rule_id": skip.id}

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

        # HTML-rendered receipts only got regex extraction above, which often
        # misses amounts living in styled tables / images (Meta Ads, Klaviyo, …).
        # When regex found no amount on a genuine (non-review) receipt, fall back
        # to the same Claude extractor the upload path uses. Gated to the failing
        # case so cost stays bounded; extract_from_pdf self-checks the API key and
        # returns an "__unavailable__" sentinel on any failure, so data is never lost.
        if chosen_source == "html_render" and meta.amount is None and not review_needed:
            try:
                from app.services.claude_extract import extract_from_pdf
                tmp_html_pdf = settings.storage_path / "tmp" / f"em-{em.id}-html.pdf"
                tmp_html_pdf.parent.mkdir(parents=True, exist_ok=True)
                tmp_html_pdf.write_bytes(chosen_pdf_bytes)
                try:
                    ext = await extract_from_pdf(tmp_html_pdf)
                finally:
                    try:
                        tmp_html_pdf.unlink()
                    except OSError:
                        pass
                if ext and ext.document_type != "__unavailable__":
                    if ext.total_amount is not None:
                        meta.amount = ext.total_amount
                    if ext.currency:
                        meta.currency = ext.currency
                    if ext.document_date and not meta.date:
                        from dateutil import parser as _dp
                        try:
                            meta.date = _dp.parse(ext.document_date)
                        except Exception:
                            pass
                    if ext.invoice_number and not meta.invoice_number:
                        meta.invoice_number = ext.invoice_number
                    log_entry["claude_extract"] = {
                        "amount": str(ext.total_amount) if ext.total_amount is not None else None,
                        "currency": ext.currency,
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "process_message.claude_extract.failed",
                    email_message_id=em.id, error=str(e),
                )

        # --- Brand routing -----------------------------------------------------
        # After we have both classification + the actual document text, check
        # whether the body identifies a known brand that belongs to a different
        # organization (e.g. Meta Ads "Transaction for FIMS" → kingnature).
        effective_org_id = em.organization_id
        brand_override: str | None = None
        haystack_for_brand = (body_text or "") + "\n" + (meta_text or "")
        route = await find_brand_route(
            db, em.organization_id, provider_id,
            em.sender_email, em.subject, haystack_for_brand, em.to_address,
        )
        if route:
            effective_org_id = route.target_organization_id
            brand_override = route.brand
            log_entry["brand_route_id"] = route.id
            log_entry["org_reassigned"] = {
                "from": em.organization_id, "to": effective_org_id, "brand": route.brand,
            }
            # Re-resolve org so template + currency follow the target org
            org = await db.get(Organization, effective_org_id)
            logger.info(
                "process_message.brand_routed",
                email_message_id=em.id, route_id=route.id,
                from_org=em.organization_id, to_org=effective_org_id, brand=route.brand,
            )

        # Resolve sub-client (against the effective org, not the source)
        sub_client = await resolve_client(db, ResolveInput(
            organization_id=effective_org_id,
            provider_id=provider_id,
            to_address=em.to_address,
            sender_email=em.sender_email,
            subject=em.subject,
            body_text=meta_text or body_text,
        ))

        # Determine final fields
        # Only fall back to the org's home currency when an amount was actually
        # extracted (a real invoice with no printed currency). If extraction came
        # up empty, leave currency NULL rather than fabricating a wrong "CHF".
        currency = meta.currency or (org.default_currency if (meta.amount is not None and org) else None)
        doc_date = meta.date or em.received_at or datetime.now(UTC)

        filename = build_filename(
            template=(org.filename_template if org else "{date}_{provider}_{client}_{amount}-{currency}"),
            date=doc_date, provider=prov_name,
            client=(sub_client.name if sub_client else None),
            amount=meta.amount, currency=currency, invoice_number=meta.invoice_number,
        )

        digest = hashlib.sha256(chosen_pdf_bytes).hexdigest()

        # --- Cross-email dedup by content hash ---------------------------------
        # If another email already produced a receipt with the exact same PDF
        # content, do NOT create a second copy (Klaviyo + Stripe both notify
        # for the same charge; Meta sometimes duplicates). Link the email to
        # the existing receipt and mark this email as finished.
        existing_by_sha = (await db.scalars(
            select(Receipt).where(
                Receipt.file_sha256 == digest,
                Receipt.email_message_id != em.id,
            )
        )).first()
        if existing_by_sha and not (existing := (await db.scalars(
            select(Receipt).where(Receipt.email_message_id == em.id)
        )).first()):
            em.status = EmailMessageStatus.finished
            log_entry["dedup_to_receipt_id"] = existing_by_sha.id
            await db.commit()
            logger.info(
                "process_message.deduped_by_sha",
                email_message_id=em.id, existing_receipt_id=existing_by_sha.id,
            )
            return {"ok": True, "deduped": True, "receipt_id": existing_by_sha.id}

        out_dir = settings.storage_path / f"org-{effective_org_id}" / f"{doc_date.year}" / f"{doc_date.month:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        # Filename-collision protection: if a different file already lives at
        # this path, append a numeric suffix so we don't overwrite real
        # content with the rendered email body.
        if out_path.exists():
            try:
                existing_bytes = out_path.read_bytes()
                if hashlib.sha256(existing_bytes).hexdigest() != digest:
                    stem, suffix = out_path.stem, out_path.suffix
                    counter = 2
                    while True:
                        candidate = out_dir / f"{stem}-{counter}{suffix}"
                        if not candidate.exists():
                            out_path = candidate
                            filename = candidate.name
                            break
                        if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
                            out_path = candidate
                            filename = candidate.name
                            break
                        counter += 1
            except OSError:
                pass
        out_path.write_bytes(chosen_pdf_bytes)

        # Persist Receipt — idempotent reprocess updates existing row.
        existing = (await db.scalars(
            select(Receipt).where(Receipt.email_message_id == em.id)
        )).first()

        layer_enum_map = {"1": ClassificationLayer.layer1, "2": ClassificationLayer.layer2, "3": ClassificationLayer.layer3}
        new_layer = layer_enum_map.get(result.layer, ClassificationLayer.layer3)

        if existing:
            existing.organization_id = effective_org_id
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
            if brand_override:
                existing.brand = brand_override
            existing.raw_metadata = {**(existing.raw_metadata or {}), "source": chosen_source, "ocr": bool(ocr_data)}
            existing.processing_log = (existing.processing_log or []) + [log_entry]
            receipt = existing
        else:
            receipt = Receipt(
                organization_id=effective_org_id,
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
                brand=brand_override,
                raw_metadata={"source": chosen_source, "ocr": bool(ocr_data)},
                processing_log=[log_entry],
            )
            db.add(receipt)

        # Payment method — the email pipeline previously never set this, so every
        # email-ingested receipt stayed "unknown". Infer from the document text;
        # if there is no explicit marker but the vendor is a known provider (our
        # catalog vendors are card-billed SaaS/ads/hosting subscriptions), default
        # to credit_card. Bank-transfer / Twint / PayPal are still detected from
        # the text first. Only fills when currently unknown, so a manual value is
        # never overwritten on reprocess.
        from app.db.models import PaymentMethod
        from app.services.payment_inference import extract_pdf_text, infer_payment_method
        try:
            if receipt.payment_method in (None, PaymentMethod.unknown):
                # extract_pdf_text expects a Path (uses .suffix) — pass out_path directly.
                inferred_pm = infer_payment_method(extract_pdf_text(out_path), filename)
                if inferred_pm is not None:
                    receipt.payment_method = inferred_pm
                elif provider_id:
                    receipt.payment_method = PaymentMethod.credit_card
        except Exception as e:  # noqa: BLE001 — payment inference must never fail the pipeline
            logger.warning("process_message.payment_infer.failed", email_message_id=em.id, error=str(e))

        em.status = EmailMessageStatus.review_needed if review_needed else EmailMessageStatus.finished
        await db.commit()
        await db.refresh(receipt)

        # Enqueue connector syncs for processed receipts
        if not review_needed:
            connectors = (await db.scalars(
                select(Connector).where(
                    # Use the post-brand-route org (== receipt.organization_id),
                    # not the mailbox's source org, so a routed receipt syncs to
                    # ITS org's connectors (matches sync_receipt_all_connectors).
                    Connector.organization_id == effective_org_id,
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


async def process_uploaded_receipt(ctx, receipt_id: int, engine: str = "auto"):
    """Extract metadata for a single uploaded receipt.

    engine:
      - "api"   : always use Claude (network)
      - "local" : always use the local Qwen LLM (no Claude fallback even on
                  failure — for testing/comparison)
      - "auto"  : try local first; fall back to Claude when local is not
                  confident or when the doc is image-only
    """
    from app.services.claude_extract import extract_path as claude_extract_path
    from app.services.local_extract import (
        extract_path as local_extract_path,
        is_confident as local_is_confident,
        _read_pdf_text,
    )
    from app.services.org_routing import RoutingInput, route

    async with SessionLocal() as db:
        r = await db.get(Receipt, receipt_id)
        if not r:
            return {"ok": False, "reason": "missing"}
        path = Path(r.file_path)
        if not path.exists():
            return {"ok": False, "reason": "file_missing"}

        ext = None
        engine_used = None
        confidence_reason = None
        if engine in ("local", "auto"):
            try:
                ext = await local_extract_path(path)
                engine_used = "local"
                if engine == "auto":
                    ok, reason = local_is_confident(ext, _read_pdf_text(path))
                    confidence_reason = reason
                    if not ok:
                        logger.info("upload.local_low_confidence",
                                    receipt_id=r.id, reason=reason)
                        ext = None  # trigger Claude fallback below
                        engine_used = None
            except Exception as e:  # noqa: BLE001
                logger.warning("upload.local_extract.failed", receipt_id=r.id, error=str(e))
                ext = None

        if ext is None and engine in ("api", "auto"):
            try:
                ext = await claude_extract_path(path)
                engine_used = "api"
            except Exception as e:  # noqa: BLE001
                logger.warning("upload.claude_extract.failed", receipt_id=r.id, error=str(e))
                ext = None

        log_entry = {
            "ts": datetime.utcnow().isoformat(),
            "event": "extracted",
            "engine_requested": engine,
            "engine_used": engine_used,
            "confidence_reason": confidence_reason,
            "document_type": getattr(ext, "document_type", None),
            "is_receipt": getattr(ext, "is_receipt", None),
            "vendor": getattr(ext, "vendor", None),
            "amount": str(getattr(ext, "total_amount", "") or ""),
            "currency": getattr(ext, "currency", None),
            "customer_hint": getattr(ext, "customer_hint", None),
        }

        # Local payment-method inference — no API cost. Runs even when Claude
        # returned nothing useful. Only overrides when (a) currently "unknown",
        # OR (b) PDF text clearly says credit_card / twint / paypal — those
        # markers are reliable and worth correcting even an existing value.
        from app.db.models import PaymentMethod
        from app.services.payment_inference import (
            extract_pdf_text, infer_payment_method,
        )
        pdf_text = extract_pdf_text(path)
        inferred_pm = infer_payment_method(pdf_text, r.filename)
        if inferred_pm and (
            r.payment_method == PaymentMethod.unknown
            or inferred_pm in (PaymentMethod.credit_card, PaymentMethod.twint, PaymentMethod.paypal)
        ):
            r.payment_method = inferred_pm
            log_entry["inferred_payment_method"] = inferred_pm.value
        elif r.payment_method == PaymentMethod.unknown and r.provider_id:
            # No explicit marker but a known (card-billed) vendor → credit_card.
            r.payment_method = PaymentMethod.credit_card
            log_entry["inferred_payment_method"] = "credit_card (provider default)"

        # API unavailable (credits, auth, render failure) — do NOT touch existing
        # receipt data. Log and return so the row keeps its current values.
        if ext and getattr(ext, "document_type", "") == "__unavailable__":
            log_entry["event"] = "claude_extract_unavailable"
            log_entry["error"] = (ext.raw or {}).get("error")
            log = list(r.processing_log or [])
            log.append(log_entry)
            r.processing_log = log
            await db.commit()
            return {"ok": False, "reason": "api_unavailable"}

        # Persist the doc-type classification regardless of receipt-ness
        if ext and getattr(ext, "document_type", None):
            from app.db.models import DocumentType
            try:
                r.document_type = DocumentType(ext.document_type)
            except ValueError:
                pass

        # Fill metadata for receipt + upcoming + document (all three may have
        # vendor/date/amount info). Only "other" is treated as no-data.
        if ext and ext.document_type in ("receipt", "upcoming", "document"):
            from dateutil import parser as _dp
            if ext.document_date:
                try:
                    r.document_date = _dp.parse(ext.document_date)
                except Exception:
                    pass
            else:
                # Claude returned no date — for uploads the initial value was
                # the upload time, which is misleading (Twint screenshots,
                # documents without a printed date, etc.). Clear it so the UI
                # shows "—" rather than today's date.
                r.document_date = None
            if ext.due_date:
                try:
                    r.due_date = _dp.parse(ext.due_date)
                except Exception:
                    pass
            else:
                # Claude says no due date — clear any stale value (avoids
                # the "issued == due" same-date bug).
                r.due_date = None
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

            # Documents and upcoming invoices auto-resolve to "processed" since
            # they're not really pending review the way an unknown-provider
            # receipt is. Receipts without a matched provider stay in review.
            if ext.document_type in ("document", "upcoming"):
                r.status = ReceiptStatus.processed
            else:
                r.status = ReceiptStatus.processed if r.provider_id else ReceiptStatus.review_needed
        elif ext and ext.document_type == "other":
            r.review_reason = "Claude: nicht klassifizierbar"

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


async def sync_receipt_to_connector(
    ctx,
    receipt_id: int,
    connector_id: int,
    mode_override: str | None = None,
):
    """Run one receipt through one connector.

    `mode_override` (e.g. "live") forces a single attempt to run in that mode
    even when the connector's saved mode differs — used by the "Promote
    dry-run to live" action from the Sync Inspector UI.
    """
    async with SessionLocal() as db:
        r = await db.get(Receipt, receipt_id)
        c = await db.get(Connector, connector_id)
        if not r or not c:
            return {"ok": False}

        try:
            effective_mode = (
                ConnectorMode(mode_override) if mode_override else c.mode
            )
        except ValueError:
            effective_mode = c.mode

        if effective_mode == ConnectorMode.off or not c.enabled:
            return {"ok": False, "skipped": True, "mode": effective_mode.value}

        cls = get_connector_class(c.type.value)
        cfg = decrypt_json(c.config_enc) or {}
        instance = cls(cfg)

        prov = await db.get(Provider, r.provider_id) if r.provider_id else None
        client = None
        if r.client_id:
            from app.db.models import Client
            client = await db.get(Client, r.client_id)

        # Per-(org × provider) bookkeeping mapping — feeds Bexio's kb_bill positions
        account_code: str | None = None
        vat_code: str | None = None
        if r.provider_id:
            mapping = (await db.scalars(select(ProviderAccountMapping).where(
                ProviderAccountMapping.provider_id == r.provider_id,
                ProviderAccountMapping.organization_id == r.organization_id,
            ))).first()
            if mapping:
                account_code = mapping.account_code
                vat_code = mapping.vat_code

        upload = ReceiptToUpload(
            receipt_id=r.id,
            organization_id=r.organization_id,
            file_path=Path(r.file_path),
            filename=r.filename,
            document_date=r.document_date or r.received_at,
            due_date=r.due_date,
            provider=(prov.display_name if prov else None),
            client=(client.name if client else None),
            amount=r.amount,
            currency=r.currency,
            invoice_number=r.invoice_number,
            vat_rate=float(r.vat_rate) if r.vat_rate is not None else None,
            vat_amount=float(r.vat_amount) if r.vat_amount is not None else None,
            account_code=account_code,
            vat_code=vat_code,
            notes=r.notes,
        )

        try:
            result: SyncResult = await instance.upload(
                upload, mode=effective_mode, auto_book=c.auto_book,
            )
        except Exception as e:  # noqa: BLE001
            result = SyncResult(ok=False, error=str(e), mode=effective_mode)

        # Upsert sync_target
        st = (await db.scalars(select(SyncTarget).where(
            SyncTarget.receipt_id == r.id, SyncTarget.connector_id == c.id,
        ))).first()
        if not st:
            st = SyncTarget(receipt_id=r.id, connector_id=c.id)
            db.add(st)

        # Audit fields — always populate so the Inspector can show what happened
        st.mode = effective_mode
        st.request_payload = result.request_payload
        st.response_payload = result.response_payload
        st.response_status_code = result.response_status_code

        if result.ok:
            if effective_mode == ConnectorMode.dry_run:
                st.status = SyncStatus.dry_run_ok
                st.synced_at = None
                st.external_id = None
            else:
                st.status = SyncStatus.synced
                st.synced_at = datetime.now(UTC)
                st.external_id = result.external_id
            st.error = result.error  # may carry a warning even on ok
            if not result.error:
                st.retry_count = 0
                st.next_retry_at = None
        else:
            st.status = SyncStatus.failed
            st.error = (result.error or "unknown")[:1000]
            st.retry_count = (st.retry_count or 0) + 1
            # exponential backoff: 2^n minutes, capped at 4h
            backoff = min(2 ** st.retry_count, 240)
            st.next_retry_at = datetime.now(UTC) + timedelta(minutes=backoff)
        await db.commit()
        return {
            "ok": result.ok,
            "external_id": result.external_id,
            "mode": effective_mode.value,
            "status": st.status.value,
        }


async def sync_receipt_all_connectors(ctx, receipt_id: int):
    async with SessionLocal() as db:
        r = await db.get(Receipt, receipt_id)
        if not r:
            return {"ok": False}
        connectors = (await db.scalars(
            select(Connector).where(
                Connector.organization_id == r.organization_id,
                Connector.enabled.is_(True),
                Connector.mode != ConnectorMode.off,
            )
        )).all()
    redis = ctx["redis"]
    for c in connectors:
        await redis.enqueue_job("sync_receipt_to_connector", receipt_id, c.id)
    return {"ok": True, "fanout": len(connectors)}
