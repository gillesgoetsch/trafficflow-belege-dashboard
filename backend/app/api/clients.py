"""Client (sub-tenant) + client_mappings CRUD."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import get_current_user
from app.db.models import Client, ClientMapping, User
from app.db.session import get_db
from app.schemas import ClientIn, ClientMappingIn, ClientMappingOut, ClientOut

router = APIRouter()


@router.get("", response_model=list[ClientOut])
async def list_clients(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    organization_id: int | None = None,
):
    q = select(Client).order_by(Client.name)
    if organization_id:
        q = q.where(Client.organization_id == organization_id)
    return (await db.scalars(q)).all()


@router.post("", response_model=ClientOut, status_code=201)
async def create_client(
    body: ClientIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    c = Client(**body.model_dump())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: int,
    body: ClientIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return c


@router.delete("/{client_id}", status_code=204)
async def delete_client(
    client_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Not found")
    await db.delete(c)
    await db.commit()


@router.get("/mappings", response_model=list[ClientMappingOut])
async def list_mappings(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    client_id: int | None = None,
):
    q = select(ClientMapping)
    if client_id:
        q = q.where(ClientMapping.client_id == client_id)
    return (await db.scalars(q)).all()


@router.post("/mappings", response_model=ClientMappingOut, status_code=201)
async def create_mapping(
    body: ClientMappingIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    m = ClientMapping(**body.model_dump())
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@router.delete("/mappings/{mapping_id}", status_code=204)
async def delete_mapping(
    mapping_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    m = await db.get(ClientMapping, mapping_id)
    if not m:
        raise HTTPException(404, "Not found")
    await db.delete(m)
    await db.commit()
