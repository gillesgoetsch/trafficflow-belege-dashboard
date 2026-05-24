"""Inbound folder CRUD + connection test + manual scan trigger."""
from __future__ import annotations

from typing import Annotated

from arq.connections import ArqRedis, create_pool, RedisSettings
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.core.encryption import decrypt_json, encrypt_json
from app.core.security import get_current_user
from app.db.models import (
    InboundFile,
    InboundFolder,
    InboundFolderType,
    User,
)
from app.db.session import get_db
from app.schemas import (
    InboundFileOut,
    InboundFolderIn,
    InboundFolderOut,
    InboundFolderPatch,
)
from app.services.inbound import build_connector

router = APIRouter()


async def _arq() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


@router.get("", response_model=list[InboundFolderOut])
async def list_folders(
    organization_id: int | None = None,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    q = select(InboundFolder).order_by(InboundFolder.id)
    if organization_id is not None:
        q = q.where(InboundFolder.organization_id == organization_id)
    rows = (await db.scalars(q)).all()
    return [InboundFolderOut.model_validate(r) for r in rows]


@router.post("", response_model=InboundFolderOut)
async def create_folder(
    payload: InboundFolderIn,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    try:
        type_ = InboundFolderType(payload.type)
    except ValueError as e:
        raise HTTPException(400, f"unknown type: {payload.type}") from e
    config = {"password": payload.password} if payload.password else None
    folder = InboundFolder(
        organization_id=payload.organization_id,
        type=type_,
        name=payload.name,
        share_url=payload.share_url,
        config_enc=encrypt_json(config) if config else None,
        batch_interval_minutes=payload.batch_interval_minutes,
        enabled=payload.enabled,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return InboundFolderOut.model_validate(folder)


@router.patch("/{folder_id}", response_model=InboundFolderOut)
async def update_folder(
    folder_id: int,
    payload: InboundFolderPatch,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    folder = await db.get(InboundFolder, folder_id)
    if not folder:
        raise HTTPException(404, "not found")
    if payload.name is not None:
        folder.name = payload.name
    if payload.share_url is not None:
        folder.share_url = payload.share_url
    if payload.batch_interval_minutes is not None:
        folder.batch_interval_minutes = payload.batch_interval_minutes
    if payload.enabled is not None:
        folder.enabled = payload.enabled
    if payload.password is not None:
        folder.config_enc = encrypt_json({"password": payload.password}) if payload.password else None
    await db.commit()
    await db.refresh(folder)
    return InboundFolderOut.model_validate(folder)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    folder = await db.get(InboundFolder, folder_id)
    if not folder:
        raise HTTPException(404, "not found")
    await db.delete(folder)
    await db.commit()


@router.post("/{folder_id}/test")
async def test_folder(
    folder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    folder = await db.get(InboundFolder, folder_id)
    if not folder:
        raise HTTPException(404, "not found")
    try:
        config = decrypt_json(folder.config_enc) if folder.config_enc else {}
    except Exception:  # noqa: BLE001
        config = {}
    try:
        conn = build_connector(folder.type, folder.share_url, config or {})
        ok, err = await conn.test()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": ok, "error": err}


@router.post("/{folder_id}/scan")
async def scan_now(
    folder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    folder = await db.get(InboundFolder, folder_id)
    if not folder:
        raise HTTPException(404, "not found")
    redis = await _arq()
    await redis.enqueue_job("scan_inbound_folder", folder.id, _job_id=f"scan_inbound:{folder.id}:manual")
    return {"ok": True, "scheduled": True}


@router.get("/{folder_id}/files", response_model=list[InboundFileOut])
async def list_folder_files(
    folder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = ...,
    _: Annotated[User, Depends(get_current_user)] = ...,
    limit: int = 100,
):
    rows = (await db.scalars(
        select(InboundFile)
        .where(InboundFile.folder_id == folder_id)
        .order_by(InboundFile.id.desc())
        .limit(limit)
    )).all()
    return [InboundFileOut.model_validate(r) for r in rows]
