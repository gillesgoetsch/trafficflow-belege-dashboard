"""Admin endpoints to manage app users + per-org access.

Roles:
- admin       — full access, can manage everything (including users).
- accountant  — read/edit receipts only for the orgs they have access to;
                cannot change settings.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, hash_password
from app.db.models import Organization, User, UserOrganization
from app.db.session import get_db

router = APIRouter()


class UserListItem(BaseModel):
    id: int
    email: EmailStr
    role: str
    is_active: bool
    organization_ids: list[int]

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = "accountant"           # admin | accountant
    organization_ids: list[int] = []   # for accountant: orgs they can see


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None
    organization_ids: list[int] | None = None


def _admin_only(user: User) -> None:
    if user.role != "admin" and not user.is_admin:
        raise HTTPException(403, "Admin only")


@router.get("", response_model=list[UserListItem])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    me: Annotated[User, Depends(get_current_user)],
):
    _admin_only(me)
    users = (await db.scalars(select(User).order_by(User.id))).all()
    items = []
    for u in users:
        org_ids = list(
            (await db.scalars(
                select(UserOrganization.organization_id).where(UserOrganization.user_id == u.id)
            )).all()
        )
        items.append(UserListItem(
            id=u.id, email=u.email, role=u.role, is_active=u.is_active,
            organization_ids=org_ids,
        ))
    return items


@router.post("", response_model=UserListItem, status_code=201)
async def create_user(
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    me: Annotated[User, Depends(get_current_user)],
):
    _admin_only(me)
    if await db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "User with that email already exists")
    u = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_admin=(body.role == "admin"),
        is_active=True,
    )
    db.add(u)
    await db.flush()
    for oid in body.organization_ids:
        db.add(UserOrganization(user_id=u.id, organization_id=oid))
    await db.commit()
    return UserListItem(
        id=u.id, email=u.email, role=u.role, is_active=u.is_active,
        organization_ids=body.organization_ids,
    )


@router.patch("/{user_id}", response_model=UserListItem)
async def update_user(
    user_id: int,
    body: UserPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
    me: Annotated[User, Depends(get_current_user)],
):
    _admin_only(me)
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Not found")
    if body.role is not None:
        u.role = body.role
        u.is_admin = body.role == "admin"
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
    if body.organization_ids is not None:
        await db.execute(delete(UserOrganization).where(UserOrganization.user_id == u.id))
        for oid in body.organization_ids:
            db.add(UserOrganization(user_id=u.id, organization_id=oid))
    await db.commit()

    org_ids = list(
        (await db.scalars(
            select(UserOrganization.organization_id).where(UserOrganization.user_id == u.id)
        )).all()
    )
    return UserListItem(
        id=u.id, email=u.email, role=u.role, is_active=u.is_active,
        organization_ids=org_ids,
    )


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    me: Annotated[User, Depends(get_current_user)],
):
    _admin_only(me)
    if user_id == me.id:
        raise HTTPException(400, "Cannot delete yourself")
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Not found")
    await db.delete(u)
    await db.commit()
