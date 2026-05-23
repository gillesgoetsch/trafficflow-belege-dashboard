"""HTML → PDF rendering via Playwright Chromium.

Sanitizes tracking pixels and marketing footer noise before rendering so the
resulting PDF is a clean receipt copy.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.core.logging import get_logger

logger = get_logger(__name__)


TRACKING_HOSTS = (
    "click.", "track.", "tracking.", "open.", "email.", "links.",
    "sendgrid.net", "list-manage.com", "mailgun.org",
    "googleadservices.com", "doubleclick.net",
)


def sanitize_html(html: str) -> str:
    """Strip tracking pixels, beacons, and footer-noise. Keep content intact."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")

    # Remove 1x1 tracking pixel images
    for img in list(soup.find_all("img")):
        src = (img.get("src") or "").lower()
        w = img.get("width", "")
        h = img.get("height", "")
        if (w in ("1", "0") and h in ("1", "0")) or any(host in src for host in TRACKING_HOSTS):
            img.decompose()

    # Remove scripts and meta refresh
    for tag in soup.find_all(["script", "meta"]):
        if tag.name == "meta" and (tag.get("http-equiv") or "").lower() == "refresh":
            tag.decompose()
        elif tag.name == "script":
            tag.decompose()

    # Inline links that look like tracking — keep the text, drop the href
    for a in soup.find_all("a"):
        href = (a.get("href") or "").lower()
        if any(host in href for host in TRACKING_HOSTS):
            a.attrs.pop("href", None)

    # Remove obvious unsubscribe footers
    for el in soup.find_all(True):
        txt = (el.get_text() or "").strip().lower()
        if not txt:
            continue
        if "unsubscribe" in txt and len(txt) < 200:
            el.decompose()

    return str(soup)


async def html_to_pdf(html: str, out_path: Path, *, title: str | None = None) -> Path:
    """Render `html` to `out_path` as A4 PDF."""
    html = sanitize_html(html or "")
    if title:
        html = f"<html><head><title>{title}</title>" \
               "<style>body{font-family:Inter,Arial,sans-serif;font-size:12pt;line-height:1.4;}" \
               "table{border-collapse:collapse;}td,th{padding:4px 8px;}</style>" \
               f"</head><body>{html}</body></html>"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            await page.emulate_media(media="print")
            await page.pdf(
                path=str(out_path),
                format="A4",
                margin={"top": "1.5cm", "bottom": "1.5cm", "left": "1.5cm", "right": "1.5cm"},
                print_background=True,
            )
        finally:
            await browser.close()
    return out_path


async def html_to_pdf_bytes(html: str) -> bytes:
    """Render to bytes (used for in-memory previews)."""
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        await html_to_pdf(html, Path(path))
        return Path(path).read_bytes()
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass
