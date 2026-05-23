"""Connector CRUD + OneDrive OAuth callback + connection test."""
from __future__ import annotations

import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.core.encryption import decrypt_json, encrypt_json
from app.core.security import get_current_user
from app.db.models import Connector, ConnectorType, User
from app.db.session import get_db
from app.schemas import ConnectorDetail, ConnectorIn, ConnectorOut
from app.services.connectors import REGISTRY, get_connector_class

router = APIRouter()


def _detail(c: Connector) -> ConnectorDetail:
    cfg = decrypt_json(c.config_enc) if c.config_enc else {}
    # never leak raw secrets to the client — mask
    safe = {}
    for k, v in (cfg or {}).items():
        if any(s in k.lower() for s in ("secret", "token", "password", "key")):
            safe[k] = "*****" if v else ""
        else:
            safe[k] = v
    return ConnectorDetail.model_validate({
        "id": c.id, "organization_id": c.organization_id, "type": c.type,
        "name": c.name, "enabled": c.enabled, "config": safe,
    })


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
):
    q = select(Connector).order_by(Connector.name)
    if organization_id:
        q = q.where(Connector.organization_id == organization_id)
    return (await db.scalars(q)).all()


@router.get("/types")
async def list_types(_: Annotated[User, Depends(get_current_user)]):
    return [
        {"type": t.value, "name": t.value.title(), "config_schema": REGISTRY[t.value].config_schema()}
        for t in ConnectorType if t.value in REGISTRY
    ]


@router.post("", response_model=ConnectorDetail, status_code=201)
async def create_connector(
    body: ConnectorIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    c = Connector(
        organization_id=body.organization_id,
        type=body.type,
        name=body.name,
        enabled=body.enabled,
        config_enc=encrypt_json(body.config or {}),
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return _detail(c)


@router.patch("/{connector_id}", response_model=ConnectorDetail)
async def update_connector(
    connector_id: int,
    body: ConnectorIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    c = await db.get(Connector, connector_id)
    if not c:
        raise HTTPException(404, "Not found")
    c.name = body.name
    c.enabled = body.enabled
    if body.config:
        existing = decrypt_json(c.config_enc) if c.config_enc else {}
        merged = {**(existing or {}), **{k: v for k, v in body.config.items() if v not in (None, "*****", "")}}
        c.config_enc = encrypt_json(merged)
    await db.commit()
    await db.refresh(c)
    return _detail(c)


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    c = await db.get(Connector, connector_id)
    if not c:
        raise HTTPException(404, "Not found")
    await db.delete(c)
    await db.commit()


@router.post("/{connector_id}/test")
async def test_connector(
    connector_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    c = await db.get(Connector, connector_id)
    if not c:
        raise HTTPException(404, "Not found")
    cls = get_connector_class(c.type.value)
    cfg = decrypt_json(c.config_enc) or {}
    try:
        ok = await cls(cfg).test()
        return {"ok": bool(ok)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# --- OneDrive OAuth flow ----------------------------------------------------


_STATE_CACHE: dict[str, dict] = {}


@router.get("/onedrive/authorize")
async def onedrive_authorize(
    organization_id: int,
    name: str = "OneDrive",
    _: Annotated[User, Depends(get_current_user)] = ...,
):
    if not settings.onedrive_client_id:
        raise HTTPException(400, "ONEDRIVE_CLIENT_ID not configured")
    state = secrets.token_urlsafe(24)
    _STATE_CACHE[state] = {"organization_id": organization_id, "name": name}
    params = {
        "client_id": settings.onedrive_client_id,
        "response_type": "code",
        "redirect_uri": settings.onedrive_redirect_uri,
        "response_mode": "query",
        "scope": "offline_access Files.ReadWrite User.Read",
        "state": state,
    }
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + urlencode(params)
    return {"authorize_url": url}


@router.get("/onedrive/callback")
async def onedrive_callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str = Query(...),
    state: str = Query(...),
):
    """Public callback — no auth dep (browser comes from Microsoft)."""
    import httpx

    info = _STATE_CACHE.pop(state, None)
    if not info:
        raise HTTPException(400, "Invalid state")

    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "client_id": settings.onedrive_client_id,
        "client_secret": settings.onedrive_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.onedrive_redirect_uri,
        "scope": "offline_access Files.ReadWrite User.Read",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_url, data=data)
        resp.raise_for_status()
        tok = resp.json()

    cfg = {
        "refresh_token": tok["refresh_token"],
        "access_token": tok.get("access_token"),
        "expires_in": tok.get("expires_in"),
        "tenant": "common",
        "folder_path": "/Belege",
    }
    c = Connector(
        organization_id=info["organization_id"],
        type=ConnectorType.onedrive,
        name=info["name"],
        config_enc=encrypt_json(cfg),
    )
    db.add(c)
    await db.commit()
    return RedirectResponse(url="/settings/connectors?onedrive=connected")
