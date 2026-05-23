"""Organization CRUD."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import get_current_user
from app.db.models import Organization, User
from app.db.session import get_db
from app.schemas import OrganizationIn, OrganizationOut

router = APIRouter()


@router.get("", response_model=list[OrganizationOut])
async def list_orgs(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    res = await db.scalars(select(Organization).order_by(Organization.name))
    return res.all()


@router.post("", response_model=OrganizationOut, status_code=201)
async def create_org(
    body: OrganizationIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    org = Organization(
        name=body.name,
        primary_email=body.primary_email,
        default_currency=body.default_currency,
        timezone=body.timezone,
    )
    if body.filename_template:
        org.filename_template = body.filename_template
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/{org_id}", response_model=OrganizationOut)
async def get_org(
    org_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return org


@router.patch("/{org_id}", response_model=OrganizationOut)
async def update_org(
    org_id: int,
    body: OrganizationIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Not found")
    org.name = body.name
    org.primary_email = body.primary_email
    org.default_currency = body.default_currency
    org.timezone = body.timezone
    if body.filename_template:
        org.filename_template = body.filename_template
    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=204)
async def delete_org(
    org_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Not found")
    await db.delete(org)
    await db.commit()
