"""Auth endpoints: login, logout, me, password change, optional TOTP."""
from __future__ import annotations

import base64
import io
from typing import Annotated

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db
from app.schemas import (
    LoginIn,
    LoginOut,
    PasswordChangeIn,
    TotpConfirmIn,
    TotpEnrollOut,
    UserOut,
)

router = APIRouter()


def _user_out(user: User) -> UserOut:
    return UserOut.model_validate(
        {
            "id": user.id,
            "email": user.email,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "totp_enabled": bool(user.totp_secret),
        }
    )


@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await db.scalar(select(User).where(User.email == body.email))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if user.totp_secret:
        if not body.otp:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OTP required")
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(body.otp, valid_window=1):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid OTP")

    token = create_access_token(user.id)
    response.set_cookie(
        "belege_session",
        token,
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    return {"access_token": token, "token_type": "bearer", "user": _user_out(user)}


@router.post("/logout")
async def logout(response: Response, _: Annotated[User, Depends(get_current_user)]):
    response.delete_cookie("belege_session", path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return _user_out(user)


@router.post("/change-password")
async def change_password(
    body: PasswordChangeIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password incorrect")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.post("/totp/enroll", response_model=TotpEnrollOut)
async def totp_enroll(user: Annotated[User, Depends(get_current_user)]):
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.app_name)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_data = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    # Stash in session-like memory? We use a temporary unconfirmed secret on the user record:
    user.totp_secret = secret + "::pending"
    return TotpEnrollOut(secret=secret, uri=uri, qr_data_url=qr_data)


@router.post("/totp/confirm")
async def totp_confirm(
    body: TotpConfirmIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not user.totp_secret or not user.totp_secret.endswith("::pending"):
        raise HTTPException(400, "No pending enrollment")
    secret = user.totp_secret.split("::", 1)[0]
    if not pyotp.TOTP(secret).verify(body.code, valid_window=1):
        raise HTTPException(400, "Invalid code")
    user.totp_secret = secret
    await db.commit()
    return {"ok": True}


@router.post("/totp/disable")
async def totp_disable(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user.totp_secret = None
    await db.commit()
    return {"ok": True}
