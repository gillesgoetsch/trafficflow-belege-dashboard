"""GitHub auto-deploy webhook receiver.

Endpoints:
  GET  /_deploy/health    — liveness
  POST /_deploy           — GitHub webhook. Verifies X-Hub-Signature-256 (HMAC-SHA256).
                            On push to $DEPLOY_BRANCH, force-pulls and rebuilds.
  POST /_deploy/trigger   — manual trigger; requires X-Token header == $DEPLOY_WEBHOOK_SECRET.
  GET  /_deploy/last      — JSON of the last deploy attempt's status.

Behavior on deploy:
  git -C /repo fetch --prune --all
  git -C /repo reset --hard origin/$BRANCH
  docker compose -f /repo/docker-compose.yml --env-file /repo/.env pull
  docker compose -f /repo/docker-compose.yml --env-file /repo/.env build api worker web
  docker compose -f /repo/docker-compose.yml --env-file /repo/.env up -d --no-deps api worker web
  docker image prune -f

The webhook serializes deploys with a lock so a noisy fast-double-push won't
interleave runs.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from aiohttp import web

LOG = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

REPO = os.environ.get("DEPLOY_REPO_PATH_IN_CONTAINER", "/repo")
BRANCH = os.environ.get("DEPLOY_BRANCH", "main")
SECRET = os.environ.get("DEPLOY_WEBHOOK_SECRET", "")
COMPOSE_SERVICES = os.environ.get("DEPLOY_SERVICES", "api worker web").split()

deploy_lock = asyncio.Lock()
last_status: dict = {"status": "idle", "ts": None, "log": []}


def _verify_signature(body: bytes, signature: str | None) -> bool:
    if not signature or not SECRET:
        return False
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _run(*cmd: str) -> tuple[int, str]:
    LOG.info("run: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        cwd=REPO,
    )
    out_b, _ = await proc.communicate()
    out = out_b.decode(errors="replace")
    LOG.info("  -> exit=%s len=%s", proc.returncode, len(out))
    return proc.returncode, out


async def _do_deploy(reason: str) -> dict:
    if deploy_lock.locked():
        return {"ok": False, "reason": "deploy_in_progress"}
    async with deploy_lock:
        result = {"status": "running", "ts": datetime.now(timezone.utc).isoformat(), "reason": reason, "log": []}
        last_status.update(result)

        steps = [
            ["git", "fetch", "--prune", "--all"],
            ["git", "reset", "--hard", f"origin/{BRANCH}"],
            ["docker", "compose", "--env-file", ".env", "pull"],
            # `--pull` re-pulls upstream base images so we don't drift; `--no-cache`
            # avoids the recurring stale-COPY-layer bug we hit a few times where
            # changed source files weren't picked up.
            ["docker", "compose", "--env-file", ".env", "build", "--pull", "--no-cache", *COMPOSE_SERVICES],
            ["docker", "compose", "--env-file", ".env", "up", "-d", "--no-deps", "--force-recreate", *COMPOSE_SERVICES],
            ["docker", "image", "prune", "-f"],
        ]
        ok = True
        for cmd in steps:
            code, out = await _run(*cmd)
            result["log"].append({"cmd": " ".join(cmd), "code": code, "tail": out[-2000:]})
            if code != 0:
                ok = False
                break
        result["status"] = "ok" if ok else "failed"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        last_status.update(result)
        return result


# --- HTTP handlers ----------------------------------------------------------


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def webhook(request: web.Request) -> web.Response:
    raw = await request.read()
    sig = request.headers.get("X-Hub-Signature-256")
    if not _verify_signature(raw, sig):
        LOG.warning("invalid signature from %s", request.remote)
        return web.json_response({"error": "invalid signature"}, status=401)

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return web.json_response({"pong": True})
    if event != "push":
        return web.json_response({"ignored": event})

    try:
        payload = json.loads(raw.decode())
    except json.JSONDecodeError:
        return web.json_response({"error": "bad json"}, status=400)

    ref = payload.get("ref", "")
    expected = f"refs/heads/{BRANCH}"
    if ref != expected:
        LOG.info("ignored ref %s (want %s)", ref, expected)
        return web.json_response({"ignored_ref": ref})

    pusher = (payload.get("pusher") or {}).get("name", "?")
    commit = (payload.get("head_commit") or {}).get("id", "?")[:7]
    reason = f"push by {pusher} ({commit})"
    LOG.info("deploy triggered: %s", reason)
    # Fire and forget — return 200 promptly.
    asyncio.create_task(_do_deploy(reason))
    return web.json_response({"accepted": True, "reason": reason})


async def manual_trigger(request: web.Request) -> web.Response:
    tok = request.headers.get("X-Token", "")
    if tok != SECRET or not SECRET:
        return web.json_response({"error": "forbidden"}, status=403)
    asyncio.create_task(_do_deploy("manual"))
    return web.json_response({"accepted": True})


async def last(request: web.Request) -> web.Response:
    return web.json_response(last_status)


def make_app() -> web.Application:
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app.router.add_get("/_deploy/health", health)
    app.router.add_get("/_deploy/last", last)
    app.router.add_post("/_deploy", webhook)
    app.router.add_post("/_deploy/trigger", manual_trigger)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=9000)
