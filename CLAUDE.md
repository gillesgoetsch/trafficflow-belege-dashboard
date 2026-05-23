# CLAUDE.md — Belege-Hub developer guide for Claude Code sessions

> This document is the source of truth for future Claude Code sessions. Read it
> before making changes. Update it whenever you make architectural changes.

## TL;DR

Self-hosted multi-tenant receipt/invoice ingestion system.

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + ARQ workers
- **Frontend**: React 18 + Vite + Tailwind + shadcn/ui + TanStack Query
- **DB**: PostgreSQL 16, **Broker**: Redis 7
- **AI**: Anthropic Claude — Haiku 4.5 (classify) + Sonnet 4.6 vision (OCR)
- **PDF render**: Playwright (Headless Chromium)
- **Reverse proxy**: Caddy 2 (auto HTTPS)
- **Deploy target**: VPS via docker compose, auto-deploy via GitHub webhook

## Repo layout

```
backend/
  app/
    main.py              FastAPI entrypoint, mounts routers, lifespan
    config.py            Pydantic Settings (reads .env)
    core/
      security.py        JWT, password hashing, current_user dep
      encryption.py      Fernet-based at-rest encryption for credentials
      logging.py         structlog JSON setup
      pagination.py
    db/
      base.py            SQLAlchemy DeclarativeBase
      session.py         async engine + session
      models.py          ALL tables (organizations, mailboxes, providers, …)
    api/
      auth.py            POST /login, /logout, /me, /change-password, /totp/*
      organizations.py   CRUD orgs
      mailboxes.py       CRUD mailboxes, test connection, trigger sync
      providers.py       CRUD providers + provider_rules
      clients.py         CRUD sub-clients + client_mappings
      receipts.py        list/detail/edit/reprocess/bulk + zip download
      review.py          review queue list + decide endpoint
      connectors.py      CRUD connectors, OneDrive OAuth flow, Bexio test
      upload.py          drag-and-drop manual upload
      dashboard.py       KPIs + charts
      deploy.py          POST /_deploy/trigger (manual)
      health.py          /api/health
    services/
      imap_fetcher.py    IMAP IDLE-capable async fetcher
      classifier.py      Layer 1 (rules) + Layer 2 (Claude Haiku)
      pdf_renderer.py    Playwright HTML→PDF with tracking-pixel stripping
      ocr.py             Claude Sonnet Vision multi-page PDF→metadata
      filename.py        normalize {date}_{provider}_{client}_{amount}-{ccy}.pdf
      multi_account.py   plus-alias + body-pattern client resolution
      attachment_parser.py extract PDFs from messages, detect scan vs digital
      pdf_metadata.py    pdfminer/pypdf metadata + native text extraction
      connectors/
        base.py          Connector ABC + registry
        local.py         filesystem connector
        onedrive.py      Microsoft Graph upload + OAuth refresh
        bexio.py         Bexio API upload as bookkeeping receipt
      notifications.py   Slack/Email webhooks on errors (Phase 5)
    workers/
      tasks.py           ARQ WorkerSettings + cron registration
      pipelines.py       receipt_pipeline (fetch → classify → render → store → sync)
    seeds.py             Seeds providers + initial 2 organizations from req §5
  alembic/               Migrations
  pyproject.toml
  Dockerfile
  alembic.ini

frontend/
  src/
    main.tsx              entrypoint + ThemeProvider (dark by default) + Router
    App.tsx               route table, auth guard
    lib/
      api.ts              fetch wrapper, auth-aware
      query.ts            TanStack Query client
      utils.ts            cn() merge + small helpers
      shortcuts.ts        global keyboard shortcut hook
      format.ts           currency/date formatters
    store/
      auth.ts             Zustand session store
      ui.ts               sidebar, command palette, theme
    types/                shared types matching backend schemas
    components/
      ui/                 shadcn primitives (button, input, dialog, …)
      layout/             AppShell, Sidebar, TopBar
      receipts/           ReceiptTable, ReceiptDetailPanel, PdfPreview
      review/             ReviewQueue, ReviewItem
      dashboard/          KpiCards, Charts
      settings/           OrganizationsList, MailboxesList, ProvidersTable, …
      common/             CommandPalette, ConfirmDialog, EmptyState
    pages/
      Login.tsx
      Dashboard.tsx
      Inbox.tsx
      ReceiptDetail.tsx (modal slide-over)
      Review.tsx
      Settings/*.tsx
      Onboarding.tsx (multi-step wizard)
      Upload.tsx
    hooks/
      useReceipts, useReview, useOrganizations, useProviders, useConnectors,
      useShortcuts, useTheme

deploy/
  Caddyfile               domain → api/web/webhook routing + HTTPS
  webhook/
    Dockerfile
    server.py             aiohttp server: HMAC-verifies GitHub push, runs
                          git pull --hard && docker compose up -d --build
    requirements.txt

scripts/
  backup.sh               pg_dump + tar of /data/receipts → S3
  init-vps.sh             one-shot VPS prep (docker, repo, .env scaffold)

docker-compose.yml        full stack (db, redis, api, worker, web, caddy, webhook, backup)
.github/workflows/        CI: lint + tests
```

## Database schema (current)

All tables `app/db/models.py`. Multi-tenant by `organization_id` FK everywhere user-data lives.

- **users** — single-user initially: `id, email, password_hash, totp_secret, is_active, created_at`
- **organizations** — `name, primary_email, default_currency, timezone`
- **mailboxes** — `organization_id, email, imap_host, imap_port, imap_user, imap_password_enc, use_tls, last_sync_at, last_uid, enabled, batch_interval_minutes`
- **providers** — global catalog. `name (slug), display_name, category, default_currency`
- **provider_rules** — `provider_id, organization_id?, match_type (sender_domain|sender_email|subject_contains|body_contains), match_value, priority`
- **clients** — sub-clients per org (`leckker`, `sichersatt`)
- **client_mappings** — `client_id, provider_id?, match_type (plus_alias|body_contains|sender_contains), match_value`
- **receipts** — the central artifact. Fields described in code; status enum `processing | processed | review_needed | archived | failed`; `classification_layer (1|2|3|manual)`; full audit trail in `processing_log JSONB`.
- **email_messages** — raw IMAP message tracking; `(mailbox_id, message_id)` UNIQUE — idempotency lever.
- **connectors** — `organization_id, type (local|onedrive|bexio), config_enc JSONB Fernet`
- **sync_targets** — `receipt_id, connector_id, status (pending|synced|failed), synced_at, error, external_id`
- **review_queue** — receipts with `status='review_needed'` are joined to this for queue ordering + reason
- **filename_templates** — per-org pattern `{date}_{provider}_{client}_{amount}-{currency}.pdf`
- **audit_log** — every state transition (Phase 5)

## Processing pipeline

The ARQ worker has two cron jobs and one queue:

1. **cron: `poll_all_mailboxes`** runs every minute, enqueues `sync_mailbox(mailbox_id)` for any mailbox whose `last_sync_at` is older than its `batch_interval_minutes`.
2. **cron: `retry_failed_syncs`** every 15 min, retries `sync_targets` in `failed` state with exponential backoff.
3. **queue: `sync_mailbox(mailbox_id)`** — connects via IMAP, walks new UIDs since `last_uid`, dedupes via `email_messages.message_id`, enqueues `process_message(email_message_id)`.
4. **queue: `process_message(email_message_id)`** — the heart:
   1. Layer 1 classifier (provider_rules) → if match, set provider + confidence=1.0, layer=1
   2. else Layer 2 (Claude Haiku) → JSON {is_receipt, provider_slug, confidence}
   3. if confidence < 0.7 or provider unknown → status=review_needed, layer=3
   4. else: extract attachments; if PDF found → store; else render HTML body to PDF via Playwright (sanitize tracking pixels + marketing footer); scanned PDFs → OCR via Sonnet Vision; resolve client via multi_account service; extract amount/date/invoice_no (regex first, else Sonnet structured extraction)
   5. write file via filename template, persist receipt row, enqueue `sync_to_connector(receipt_id, connector_id)` for each org connector
5. **queue: `sync_to_connector`** — calls Connector.upload(receipt) and writes sync_targets row.

The pipeline is fully idempotent — re-running on the same `email_message_id` is safe.

## Auth model

- Initial single admin user, created from `ADMIN_EMAIL`/`ADMIN_PASSWORD` on first boot (see `seeds.py`).
- Login: `POST /api/auth/login` returns `{access_token}` AND sets `belege_session` HttpOnly cookie.
- All protected endpoints depend on `current_user`.
- TOTP optional: enroll via `/api/auth/totp/enroll` → QR → confirm; once enabled, login requires `otp` param.

## Encryption

All credentials (IMAP passwords, OAuth refresh tokens, Bexio API keys) are encrypted with **Fernet** before DB write, using `ENCRYPTION_KEY` from env. See `app/core/encryption.py` — never store unencrypted secrets.

## Frontend conventions

- Dark mode is the default; light mode toggle in topbar.
- Cmd+K opens the global command palette (jumps + actions).
- `j/k` navigate inbox rows, `Enter` opens detail, `Shift+Click` for bulk select, `?` shows shortcut help, `g i`/`g d`/`g r`/`g s` jump to Inbox/Dashboard/Review/Settings.
- All data fetching via TanStack Query; optimistic updates for tagging/status changes.
- Forms use react-hook-form + zod schemas matching backend pydantic.
- Toasts via shadcn's `useToast`.

## Onboarding wizard

`/onboarding` route. 5 steps:
1. Organization details
2. Add at least one mailbox (test connection inline)
3. Add a connector (or skip)
4. Trigger "test scan: last 30 days" — shows realtime progress
5. Review classifications + accept suggested whitelist rules

## Adding a new connector

1. Subclass `app/services/connectors/base.Connector`
2. Implement `upload(receipt) -> SyncResult` and `test() -> bool`
3. Register in `connectors/__init__.py` `REGISTRY`
4. Add UI form in `frontend/src/components/settings/ConnectorForms/`

No core changes needed — connectors are pluggable.

## Adding a new provider

You can fully manage providers from the UI (Settings → Providers). Programmatically, append to `app/seeds.py:PROVIDER_SEEDS`. Provider rules can match `sender_domain`, `sender_email`, `subject_contains`, or `body_contains` — pick the most specific one available.

## Auto-deploy

GitHub → webhook at `/_deploy` → `deploy/webhook/server.py`:

1. Verifies `X-Hub-Signature-256` HMAC using `DEPLOY_WEBHOOK_SECRET`
2. Drops payloads that aren't push events to `DEPLOY_BRANCH`
3. Runs (in serialized lock):
   ```bash
   git -C /repo fetch --all
   git -C /repo reset --hard origin/$BRANCH
   docker compose -f /repo/docker-compose.yml build api worker web
   docker compose -f /repo/docker-compose.yml up -d --no-deps api worker web
   docker image prune -f
   ```
4. Posts status back to GitHub commit (Phase 5).

The webhook container mounts `/var/run/docker.sock` and `/srv/belege` (host repo). Caddy exposes only `/_deploy` and `/_deploy/trigger` paths from it.

## Backups

Cron in `backup` service (3am daily):

- `pg_dump` of postgres
- `tar -cJ` of `/data/receipts`
- `aws s3 cp` to `s3://$BACKUP_S3_BUCKET/` (configurable endpoint, e.g. Cloudflare R2 or Backblaze B2)
- Skipped silently if `BACKUP_S3_BUCKET` is empty.

## Local dev (no docker)

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
export DATABASE_URL=postgresql+psycopg://belege:belege@localhost/belege
alembic upgrade head
python -m app.seeds
uvicorn app.main:app --reload

# worker
arq app.workers.tasks.WorkerSettings

# frontend
cd frontend
pnpm i && pnpm dev    # proxies /api to localhost:8000
```

## Operational notes

- **Logs**: structlog JSON. `docker compose logs api worker` to follow.
- **Metrics**: `/api/metrics` is Prometheus-format; scrape internally only.
- **DB migrations**: `docker compose exec api alembic revision --autogenerate -m "..."` then commit.
- **Re-process a receipt**: from detail panel "Reprocess" button → enqueues `process_message` again.
- **Re-sync to connectors**: bulk action in inbox.
- **Force IMAP re-scan from scratch**: Settings → Mailbox → "Reset cursor" sets `last_uid=0`.

## Phase status

- ✅ Phase 1 — MVP foundation, IMAP, Layer 1, local storage, single-user auth
- ✅ Phase 2 — Layer 2 (Haiku), Review queue, HTML→PDF, OCR (Sonnet Vision), sub-client
- ✅ Phase 3 — OneDrive + Bexio connectors, re-sync/re-process
- ✅ Phase 4 — Dashboard charts, bulk actions, shortcuts, mobile-responsive, onboarding wizard
- 🚧 Phase 5 — Google Ads API puller, multi-user roles, external webhooks, drag-and-drop upload (drag-drop is in), error notifications

## Known TODOs / Gotchas

- Google Ads API-puller is stubbed (`app/services/api_pullers/google_ads.py`) — needs credentials wiring + UI.
- Caddy uses real Let's Encrypt; for local dev you can run `caddy run --config Caddyfile.local` (sets `local_certs`).
- Playwright Chromium download is ~120MB on first build — the backend image includes it.
- The webhook trusts `/repo` being a clean checkout; if you've made local hot-fixes on the VPS, push them or they will be reset.
