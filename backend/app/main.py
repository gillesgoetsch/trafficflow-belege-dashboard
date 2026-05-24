"""FastAPI app entry point. Mounts all routers, sets up middleware + lifespan."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.api import (
    auth,
    clients,
    connectors,
    dashboard,
    deploy,
    health,
    inbound_folders,
    mailboxes,
    org_routing as org_routing_api,
    organizations,
    providers,
    receipts,
    review,
    sync_targets,
    upload,
    users as users_api,
)
from app.config import settings
from app.core.logging import get_logger, setup as setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("app.start", env=settings.app_env, base=settings.app_base_url)
    # Ensure storage dir exists
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("app.stop")


app = FastAPI(
    title="Belege-Hub API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS — Caddy handles same-origin in prod; permissive for dev with credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", settings.app_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- Routers ----------------------------------------------------------------

api_prefix = "/api"
app.include_router(health.router, prefix=api_prefix)
app.include_router(auth.router, prefix=f"{api_prefix}/auth", tags=["auth"])
app.include_router(organizations.router, prefix=f"{api_prefix}/organizations", tags=["organizations"])
app.include_router(mailboxes.router, prefix=f"{api_prefix}/mailboxes", tags=["mailboxes"])
app.include_router(providers.router, prefix=f"{api_prefix}/providers", tags=["providers"])
app.include_router(clients.router, prefix=f"{api_prefix}/clients", tags=["clients"])
app.include_router(receipts.router, prefix=f"{api_prefix}/receipts", tags=["receipts"])
app.include_router(review.router, prefix=f"{api_prefix}/review", tags=["review"])
app.include_router(connectors.router, prefix=f"{api_prefix}/connectors", tags=["connectors"])
app.include_router(sync_targets.router, prefix=f"{api_prefix}/sync-targets", tags=["sync-targets"])
app.include_router(upload.router, prefix=f"{api_prefix}/upload", tags=["upload"])
app.include_router(dashboard.router, prefix=f"{api_prefix}/dashboard", tags=["dashboard"])
app.include_router(users_api.router, prefix=f"{api_prefix}/users", tags=["users"])
app.include_router(org_routing_api.router, prefix=f"{api_prefix}/org-routing", tags=["org-routing"])
app.include_router(inbound_folders.router, prefix=f"{api_prefix}/inbound-folders", tags=["inbound-folders"])
app.include_router(deploy.router, prefix="/_deploy", tags=["deploy"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    logger.exception("api.unhandled", path=request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
