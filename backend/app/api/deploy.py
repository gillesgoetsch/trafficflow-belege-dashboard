"""Lightweight endpoints to peek and manually trigger the deploy webhook.

The actual GitHub webhook receiver runs in the separate `webhook` container
(see deploy/webhook/) — these endpoints are operator convenience only.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import settings
from app.core.security import get_current_user
from app.db.models import User

router = APIRouter()


@router.get("/status")
async def status(_: Annotated[User, Depends(get_current_user)]):
    return {
        "branch": settings.deploy_branch,
        "repo_path": settings.deploy_repo_path,
        "webhook_url": settings.app_base_url.rstrip("/") + "/_deploy",
    }


@router.post("/trigger")
async def trigger(
    _: Annotated[User, Depends(get_current_user)],
    x_token: Annotated[str | None, Header(alias="X-Token")] = None,
):
    if x_token != settings.deploy_webhook_secret:
        raise HTTPException(403, "Invalid token")
    # Forwarded to the webhook container by Caddy; the API container itself
    # has no docker socket. Provide explicit guidance.
    return {
        "ok": True,
        "note": "Trigger by calling the webhook service: curl -X POST $BASE/_deploy/trigger -H 'X-Token: ...'",
    }
