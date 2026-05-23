"""CRUD for organization_routing_rules.

These rules teach the system which organization a receipt belongs to when one
mailbox is shared across multiple legal entities. Patterns are simple
substring matches against body / sender / subject (case-insensitive).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import get_current_user
from app.db.models import OrganizationRoutingRule, User
from app.db.session import get_db

router = APIRouter()

MATCH_TYPES = {"body_contains", "sender_contains", "subject_contains", "sender_domain"}


class RuleIn(BaseModel):
    organization_id: int
    match_type: str = Field(pattern="^(body_contains|sender_contains|subject_contains|sender_domain)$")
    match_value: str
    priority: int = 100


class RuleOut(BaseModel):
    id: int
    organization_id: int
    match_type: str
    match_value: str
    priority: int

    class Config:
        from_attributes = True


@router.get("", response_model=list[RuleOut])
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
):
    q = select(OrganizationRoutingRule).order_by(OrganizationRoutingRule.priority.desc(), OrganizationRoutingRule.id)
    if organization_id:
        q = q.where(OrganizationRoutingRule.organization_id == organization_id)
    return (await db.scalars(q)).all()


@router.post("", response_model=RuleOut, status_code=201)
async def create_rule(
    body: RuleIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    if body.match_type not in MATCH_TYPES:
        raise HTTPException(400, "Bad match_type")
    r = OrganizationRoutingRule(**body.model_dump())
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


@router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: int,
    body: RuleIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(OrganizationRoutingRule, rule_id)
    if not r:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    await db.commit()
    await db.refresh(r)
    return r


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.get(OrganizationRoutingRule, rule_id)
    if not r:
        raise HTTPException(404, "Not found")
    await db.delete(r)
    await db.commit()
