"""ARQ task definitions + WorkerSettings.

Cron jobs:
  * poll_all_mailboxes (every minute) — enqueues sync_mailbox for due ones.
  * retry_failed_syncs (every 15 minutes) — re-enqueues failed sync_targets.

Queued jobs:
  * sync_mailbox(mailbox_id)
  * process_message(email_message_id, force=False)
  * process_uploaded_receipt(receipt_id)
  * sync_receipt_to_connector(receipt_id, connector_id)
  * sync_receipt_all_connectors(receipt_id)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.core.logging import get_logger, setup as setup_logging
from app.workers.pipelines import (
    poll_all_mailboxes,
    process_message,
    process_uploaded_receipt,
    requeue_stuck_emails,
    retry_failed_syncs,
    sync_mailbox,
    sync_receipt_all_connectors,
    sync_receipt_to_connector,
)

logger = get_logger(__name__)


async def on_startup(ctx):
    setup_logging()
    logger.info("worker.start")


async def on_shutdown(ctx):
    logger.info("worker.stop")


class WorkerSettings:
    functions = [
        sync_mailbox,
        process_message,
        process_uploaded_receipt,
        sync_receipt_to_connector,
        sync_receipt_all_connectors,
        poll_all_mailboxes,
        retry_failed_syncs,
        requeue_stuck_emails,
    ]
    cron_jobs = [
        cron(poll_all_mailboxes, minute=set(range(0, 60))),  # every minute
        cron(retry_failed_syncs, minute={0, 15, 30, 45}),
        # Catch emails that got into email_messages but whose process_message
        # job was lost (e.g. worker killed during a deploy). Runs every 3 min.
        cron(requeue_stuck_emails, minute={0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57}),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 600
    keep_result = 3600
    max_jobs = 5
    on_startup = on_startup
    on_shutdown = on_shutdown
