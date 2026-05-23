"""Async IMAP fetching helpers.

Strategy:
  * Connect via aioimaplib (TLS preferred).
  * Use `UID SEARCH UID <last_uid+1>:*` to enumerate new UIDs.
  * For each new UID, fetch raw RFC822 + dedupe by Message-ID.
  * Persist `email_messages` rows; downstream worker queues processing.
"""
from __future__ import annotations

import asyncio
import email
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message as EmailMessageObj
from email.utils import parsedate_to_datetime
from pathlib import Path

import aioimaplib
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _decode(s: str | None) -> str | None:
    if not s:
        return s
    parts = decode_header(s)
    out = []
    for txt, charset in parts:
        if isinstance(txt, bytes):
            try:
                out.append(txt.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(txt.decode("utf-8", errors="replace"))
        else:
            out.append(txt)
    return "".join(out)


@dataclass
class FetchedMessage:
    uid: int
    message_id: str
    subject: str | None
    sender_name: str | None
    sender_email: str | None
    to_address: str | None
    received_at: datetime | None
    raw_size: int
    raw_path: str


async def test_connection(*, host: str, port: int, user: str, password: str, use_tls: bool) -> tuple[bool, str | None]:
    try:
        client = aioimaplib.IMAP4_SSL(host=host, port=port, timeout=15) if use_tls else aioimaplib.IMAP4(host=host, port=port, timeout=15)
        await client.wait_hello_from_server()
        resp = await client.login(user, password)
        if resp.result != "OK":
            return False, "Login failed"
        await client.logout()
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _parse_address(value: str | None) -> tuple[str | None, str | None]:
    """Return (name, email) tuple from a From/To header."""
    if not value:
        return None, None
    from email.utils import parseaddr
    name, addr = parseaddr(value)
    return (_decode(name) or None), (addr or None)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
async def fetch_new_messages(
    *, host: str, port: int, user: str, password: str,
    use_tls: bool, folder: str, last_uid: int, raw_dir: Path, limit: int = 200,
) -> list[FetchedMessage]:
    """Connect and return list of newly-fetched messages with bodies on disk."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    client = aioimaplib.IMAP4_SSL(host=host, port=port, timeout=30) if use_tls else aioimaplib.IMAP4(host=host, port=port, timeout=30)
    await client.wait_hello_from_server()
    resp = await client.login(user, password)
    if resp.result != "OK":
        raise RuntimeError("IMAP login failed")
    try:
        sel = await client.select(folder)
        if sel.result != "OK":
            raise RuntimeError(f"IMAP select failed: {folder}")

        search_query = f"UID {last_uid + 1}:*" if last_uid > 0 else "ALL"
        search = await client.uid_search(search_query)
        if search.result != "OK":
            return []
        uids = [int(u) for u in search.lines[0].split() if u.isdigit()]
        uids = sorted(set(uids))
        # When `UID n:*` is used and no messages exist >n, the server returns
        # the highest UID. Filter those that are <= last_uid.
        uids = [u for u in uids if u > last_uid][:limit]

        results: list[FetchedMessage] = []
        for uid in uids:
            fetch = await client.uid("fetch", str(uid), "(RFC822)")
            if fetch.result != "OK":
                continue
            raw_bytes = _extract_rfc822(fetch.lines)
            if not raw_bytes:
                continue
            msg = email.message_from_bytes(raw_bytes)
            mid = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip("<>") or f"no-msgid-uid-{uid}"
            subj = _decode(msg.get("Subject"))
            sname, semail = _parse_address(msg.get("From"))
            to_addr = msg.get("To") or msg.get("Delivered-To")
            dt: datetime | None = None
            if msg.get("Date"):
                try:
                    dt = parsedate_to_datetime(msg["Date"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    dt = None

            fd, path = tempfile.mkstemp(dir=raw_dir, prefix=f"msg-{uid}-", suffix=".eml")
            with os.fdopen(fd, "wb") as f:
                f.write(raw_bytes)
            results.append(FetchedMessage(
                uid=uid, message_id=mid, subject=subj,
                sender_name=sname, sender_email=semail,
                to_address=to_addr, received_at=dt,
                raw_size=len(raw_bytes), raw_path=path,
            ))
        return results
    finally:
        try:
            await client.logout()
        except Exception:
            pass


def _extract_rfc822(lines: list[bytes]) -> bytes | None:
    """aioimaplib returns the raw payload split across several lines.
    The body is the longest binary chunk in the response."""
    if not lines:
        return None
    blobs = [l for l in lines if isinstance(l, (bytes, bytearray))]
    if not blobs:
        return None
    # Concatenate all bytes between the parenthesis lines; the
    # last/largest chunk is the body.
    return max(blobs, key=len)


def load_email_from_path(path: str) -> EmailMessageObj:
    with open(path, "rb") as f:
        return email.message_from_bytes(f.read())


def extract_html_text(msg: EmailMessageObj) -> tuple[str | None, str | None]:
    """Return (html_body, plain_body)."""
    html: str | None = None
    plain: str | None = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/html" and html is None:
            html = _decode_payload(part)
        elif ctype == "text/plain" and plain is None:
            plain = _decode_payload(part)
    return html, plain


def _decode_payload(part: EmailMessageObj) -> str | None:
    try:
        data = part.get_payload(decode=True)
        if data is None:
            return None
        charset = part.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")
    except Exception:
        return None


def extract_pdf_attachments(msg: EmailMessageObj) -> list[tuple[str, bytes]]:
    """Return list of (filename, bytes) for every PDF-like attachment."""
    out: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        if filename:
            filename = _decode(filename) or filename
        is_pdf = (
            ctype == "application/pdf"
            or (filename and filename.lower().endswith(".pdf"))
            or "attachment" in disposition and filename
        )
        if is_pdf:
            data = part.get_payload(decode=True)
            if data:
                out.append((filename or "attachment.pdf", data))
    return out


def extract_image_attachments(msg: EmailMessageObj) -> list[tuple[str, bytes, str]]:
    out: list[tuple[str, bytes, str]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        if ctype.startswith("image/"):
            data = part.get_payload(decode=True)
            if data:
                name = part.get_filename() or f"image{ctype.replace('image/', '.')}"
                out.append((name, data, ctype))
    return out
