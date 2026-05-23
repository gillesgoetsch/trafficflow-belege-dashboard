# Belege-Hub

Self-hosted webapp that watches IMAP mailboxes, classifies and consolidates receipts/invoices, and pushes them to OneDrive / Bexio / local storage.

Deployed at **https://belege.trafficflow.ch**.

## Quick Start (Local Dev)

```bash
cp .env.example .env
# edit .env: fill SECRET_KEY, ENCRYPTION_KEY, ANTHROPIC_API_KEY, ADMIN_PASSWORD

docker compose up -d --build
docker compose logs -f api worker
```

Open http://localhost (Caddy proxies to api+web). For raw dev:

```bash
# Backend
cd backend && uv venv && uv sync && uv run uvicorn app.main:app --reload
# Frontend
cd frontend && pnpm i && pnpm dev
```

## Production Deploy (VPS)

```bash
# On the VPS (Ubuntu 22.04+/Debian 12)
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo mkdir -p /srv/belege && sudo chown $USER /srv/belege
git clone https://github.com/<your-user>/trafficflow-belege-dashboard /srv/belege
cd /srv/belege
cp .env.example .env && vi .env  # fill secrets, domain, repo path
docker compose up -d --build
```

DNS: point `belege.trafficflow.ch` (A/AAAA) at the VPS. Caddy auto-issues Let's Encrypt cert on first hit.

### GitHub auto-deploy webhook

1. In GitHub repo → Settings → Webhooks → Add webhook
2. Payload URL: `https://belege.trafficflow.ch/_deploy`
3. Content type: `application/json`
4. Secret: same value as `DEPLOY_WEBHOOK_SECRET` in `.env`
5. Events: just the `push` event
6. Active: yes

On every push to `main` (configurable via `DEPLOY_BRANCH`), the webhook service force-pulls, rebuilds the affected images, and rolls a zero-downtime restart.

Manual trigger from VPS:

```bash
curl -X POST http://localhost/_deploy/trigger -H "X-Token: $DEPLOY_WEBHOOK_SECRET"
```

## Architecture

See [CLAUDE.md](./CLAUDE.md) for the deep dive intended for future Claude Code sessions.

```
┌─────────┐    ┌──────────────────────────────┐
│ Caddy   │ ─► │ /api  → FastAPI (uvicorn)    │
│ TLS     │    │ /     → React build (static) │
│         │    │ /_deploy → GitHub webhook    │
└─────────┘    └──────────────────────────────┘
                    │
                    ▼
              ┌─────────────┐    ┌─────────┐
              │ PostgreSQL  │◄───┤ ARQ     │
              │             │    │ worker  │── IMAP polls, LLM calls,
              └─────────────┘    └─────────┘   PDF render, connector syncs
                    ▲                 ▲
                    └─── Redis ───────┘
```

## Tech Stack

| Layer        | Choice                                          |
|--------------|-------------------------------------------------|
| Backend      | Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic  |
| Worker       | ARQ (Redis-based async task queue)              |
| LLM          | Anthropic Claude (Haiku 4.5 + Sonnet 4.6 vision)|
| PDF render   | Playwright (Headless Chromium)                  |
| DB           | PostgreSQL 16                                   |
| Frontend     | React 18 + TypeScript + Vite + Tailwind         |
| UI kit       | shadcn/ui (Radix) + lucide icons                |
| State/data   | TanStack Query + Zustand                        |
| Auth         | JWT (HttpOnly cookie) + bcrypt + optional TOTP  |
| Reverse proxy| Caddy 2 (auto Let's Encrypt)                    |
| Container    | Docker Compose                                  |
| Auto-deploy  | Custom HMAC-verified GitHub webhook receiver    |

## Repo layout

```
.
├── backend/        FastAPI app, models, workers, connectors
├── frontend/       React SPA
├── deploy/         Caddyfile, webhook service
├── scripts/        backup, init helpers
├── docker-compose.yml
├── CLAUDE.md       full architecture + dev guide
└── README.md
```
