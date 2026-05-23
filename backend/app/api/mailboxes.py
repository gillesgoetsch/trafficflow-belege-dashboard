"""Mailbox CRUD + connection test + manual sync trigger."""
from __future__ import annotations

from typing import Annotated

from arq.connections import ArqRedis, create_pool, RedisSettings
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.core.encryption import decrypt_str, encrypt_str
from app.core.security import get_current_user
from app.db.models import Mailbox, User
from app.db.session import get_db
from app.schemas import MailboxIn, MailboxOut, MailboxPatch
from app.services.imap_fetcher import test_connection

router = APIRouter()


async def _arq() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


@router.get("", response_model=list[MailboxOut])
async def list_mailboxes(
    organization_id: int | None = None,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    q = select(Mailbox).order_by(Mailbox.email)
    if organization_id:
        q = q.where(Mailbox.organization_id == organization_id)
    res = await db.scalars(q)
    return res.all()


@router.post("", response_model=MailboxOut, status_code=201)
async def create_mailbox(
    body: MailboxIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    mb = Mailbox(
        organization_id=body.organization_id,
        email=body.email,
        imap_host=body.imap_host,
        imap_port=body.imap_port,
        imap_user=body.imap_user,
        imap_password_enc=encrypt_str(body.imap_password),
        use_tls=body.use_tls,
        folder=body.folder,
        batch_interval_minutes=body.batch_interval_minutes,
        enabled=body.enabled,
    )
    db.add(mb)
    await db.commit()
    await db.refresh(mb)
    return mb


@router.patch("/{mailbox_id}", response_model=MailboxOut)
async def update_mailbox(
    mailbox_id: int,
    body: MailboxPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    mb = await db.get(Mailbox, mailbox_id)
    if not mb:
        raise HTTPException(404, "Not found")
    data = body.model_dump(exclude_unset=True)
    if "imap_password" in data:
        mb.imap_password_enc = encrypt_str(data.pop("imap_password"))
    for k, v in data.items():
        setattr(mb, k, v)
    await db.commit()
    await db.refresh(mb)
    return mb


@router.delete("/{mailbox_id}", status_code=204)
async def delete_mailbox(
    mailbox_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    mb = await db.get(Mailbox, mailbox_id)
    if not mb:
        raise HTTPException(404, "Not found")
    await db.delete(mb)
    await db.commit()


@router.post("/{mailbox_id}/test")
async def test_mailbox(
    mailbox_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    mb = await db.get(Mailbox, mailbox_id)
    if not mb:
        raise HTTPException(404, "Not found")
    ok, err = await test_connection(
        host=mb.imap_host,
        port=mb.imap_port,
        user=mb.imap_user,
        password=decrypt_str(mb.imap_password_enc),
        use_tls=mb.use_tls,
    )
    return {"ok": ok, "error": err}


@router.post("/{mailbox_id}/sync")
async def trigger_sync(
    mailbox_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    mb = await db.get(Mailbox, mailbox_id)
    if not mb:
        raise HTTPException(404, "Not found")
    pool = await _arq()
    job = await pool.enqueue_job("sync_mailbox", mb.id)
    return {"ok": True, "job_id": job.job_id if job else None}


@router.post("/{mailbox_id}/reset-cursor")
async def reset_cursor(
    mailbox_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    mb = await db.get(Mailbox, mailbox_id)
    if not mb:
        raise HTTPException(404, "Not found")
    mb.last_uid = 0
    mb.last_sync_at = None
    await db.commit()
    return {"ok": True}
