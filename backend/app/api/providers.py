"""Provider + provider_rules CRUD."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import get_current_user
from app.db.models import (
    Provider,
    ProviderAccountMapping,
    ProviderRule,
    User,
)
from app.db.session import get_db
from app.schemas import (
    ProviderAccountMappingIn,
    ProviderAccountMappingOut,
    ProviderIn,
    ProviderOut,
    ProviderRuleIn,
    ProviderRuleOut,
)

router = APIRouter()


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    res = await db.scalars(select(Provider).order_by(Provider.display_name))
    return res.all()


@router.post("", response_model=ProviderOut, status_code=201)
async def create_provider(
    body: ProviderIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    p = Provider(**body.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int,
    body: ProviderIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    p = await db.get(Provider, provider_id)
    if not p:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return p


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    p = await db.get(Provider, provider_id)
    if not p:
        raise HTTPException(404, "Not found")
    await db.delete(p)
    await db.commit()


@router.get("/rules", response_model=list[ProviderRuleOut])
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    provider_id: int | None = None,
    organization_id: int | None = None,
):
    q = select(ProviderRule).order_by(ProviderRule.priority.desc())
    if provider_id:
        q = q.where(ProviderRule.provider_id == provider_id)
    if organization_id:
        q = q.where(ProviderRule.organization_id == organization_id)
    res = await db.scalars(q)
    return res.all()


@router.post("/rules", response_model=ProviderRuleOut, status_code=201)
async def create_rule(
    body: ProviderRuleIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = ProviderRule(**body.model_dump())
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


@router.patch("/rules/{rule_id}", response_model=ProviderRuleOut)
async def update_rule(
    rule_id: int,
    body: ProviderRuleIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(ProviderRule, rule_id)
    if not r:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    await db.commit()
    await db.refresh(r)
    return r


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(ProviderRule, rule_id)
    if not r:
        raise HTTPException(404, "Not found")
    await db.delete(r)
    await db.commit()


# --- Provider × Organization account mappings (Bexio kb_bill auto-fill) -----


@router.get("/account-mappings", response_model=list[ProviderAccountMappingOut])
async def list_account_mappings(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
    provider_id: int | None = None,
):
    q = select(ProviderAccountMapping)
    if organization_id:
        q = q.where(ProviderAccountMapping.organization_id == organization_id)
    if provider_id:
        q = q.where(ProviderAccountMapping.provider_id == provider_id)
    res = await db.scalars(q)
    return res.all()


@router.post("/account-mappings", response_model=ProviderAccountMappingOut, status_code=201)
async def upsert_account_mapping(
    body: ProviderAccountMappingIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Create or update the (org, provider) → (account_code, vat_code) mapping.

    POST semantics are upsert by (organization_id, provider_id) — the UI just
    sends the desired state and we sync it.
    """
    existing = (await db.scalars(select(ProviderAccountMapping).where(
        ProviderAccountMapping.provider_id == body.provider_id,
        ProviderAccountMapping.organization_id == body.organization_id,
    ))).first()
    if existing:
        existing.account_code = body.account_code
        existing.vat_code = body.vat_code
        m = existing
    else:
        m = ProviderAccountMapping(**body.model_dump())
        db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@router.delete("/account-mappings/{mapping_id}", status_code=204)
async def delete_account_mapping(
    mapping_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    m = await db.get(ProviderAccountMapping, mapping_id)
    if not m:
        raise HTTPException(404, "Not found")
    await db.delete(m)
    await db.commit()
