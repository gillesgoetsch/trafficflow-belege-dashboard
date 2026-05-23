"""Provider + provider_rules CRUD."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import get_current_user
from app.db.models import Provider, ProviderRule, User
from app.db.session import get_db
from app.schemas import ProviderIn, ProviderOut, ProviderRuleIn, ProviderRuleOut

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
