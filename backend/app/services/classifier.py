"""3-layer classifier.

Layer 1: deterministic rules from `provider_rules` (sender_domain / sender_email /
         subject_contains / body_contains). Cheap and exact.
Layer 2: Claude Haiku 4.5 LLM. Decides {is_receipt, provider_slug, confidence}.
Layer 3: anything below the confidence threshold or with unknown provider goes to
         the review queue (signaled by the caller).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.core.logging import get_logger
from app.db.models import MatchType, Provider, ProviderRule

logger = get_logger(__name__)


CONFIDENCE_THRESHOLD = 0.7


@dataclass
class ClassificationInput:
    sender_email: str | None
    sender_name: str | None
    subject: str | None
    body_text: str | None
    organization_id: int


@dataclass
class ClassificationResult:
    is_receipt: bool
    provider_slug: str | None
    provider_id: int | None
    layer: str  # "1" | "2" | "3"
    confidence: float
    rule_id: int | None = None
    notes: str | None = None


# --- Layer 1 ----------------------------------------------------------------


async def layer1(db: AsyncSession, inp: ClassificationInput) -> ClassificationResult | None:
    """Apply provider_rules. Returns a result iff some rule matched."""
    rules = (await db.scalars(
        select(ProviderRule)
        .where((ProviderRule.organization_id == inp.organization_id) | (ProviderRule.organization_id.is_(None)))
        .order_by(ProviderRule.priority.desc())
    )).all()

    sender_email = (inp.sender_email or "").lower()
    sender_domain = sender_email.split("@", 1)[-1] if "@" in sender_email else ""
    subject = (inp.subject or "").lower()
    body = (inp.body_text or "").lower()

    for r in rules:
        v = (r.match_value or "").lower().strip()
        if not v:
            continue
        hit = False
        if r.match_type == MatchType.sender_domain:
            hit = sender_domain.endswith(v)
        elif r.match_type == MatchType.sender_email:
            hit = sender_email == v
        elif r.match_type == MatchType.sender_contains:
            hit = v in sender_email
        elif r.match_type == MatchType.subject_contains:
            hit = v in subject
        elif r.match_type == MatchType.body_contains:
            hit = v in body
        if hit:
            return ClassificationResult(
                is_receipt=True,
                provider_slug=None,
                provider_id=r.provider_id,
                layer="1",
                confidence=1.0,
                rule_id=r.id,
            )
    return None


# --- Layer 2 ----------------------------------------------------------------

_SYSTEM_PROMPT = """You classify business emails as receipts/invoices for an SMB accounting system.

Return STRICT JSON only with this shape:
{
  "is_receipt": true|false,
  "provider_slug": "lowercase-kebab-vendor-slug" | null,
  "confidence": 0.0..1.0,
  "reasoning": "short string"
}

Rules:
- A receipt/invoice/payment confirmation/Rechnung/Quittung/Zahlungsbestätigung qualifies.
- Marketing emails, signup confirmations, password resets, newsletters DO NOT.
- Pick provider_slug from a normalized form of the sender's company name
  (e.g. "facebook-ads", "google-ads", "spotify", "infomaniak", "bexio", "openai").
- If unsure, set is_receipt=false with low confidence."""


def _trim(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return text[:limit]


async def layer2(inp: ClassificationInput) -> ClassificationResult:
    """LLM-based classification with Claude Haiku 4.5."""
    if not settings.anthropic_api_key:
        # Fail closed: send to review queue.
        return ClassificationResult(
            is_receipt=False, provider_slug=None, provider_id=None,
            layer="3", confidence=0.0, notes="anthropic_api_key_missing",
        )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_msg = (
        f"From: {inp.sender_name or ''} <{inp.sender_email or ''}>\n"
        f"Subject: {_trim(inp.subject, 300)}\n\n"
        f"Body (first 2000 chars):\n{_trim(inp.body_text, 2000)}"
    )

    try:
        resp = await client.messages.create(
            model=settings.classifier_model,
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = ""
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                text += block.text
        data = _coerce_json(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("classifier.layer2.error", error=str(e))
        return ClassificationResult(
            is_receipt=False, provider_slug=None, provider_id=None,
            layer="3", confidence=0.0, notes=f"layer2_error: {e}",
        )

    is_receipt = bool(data.get("is_receipt"))
    slug = data.get("provider_slug")
    conf = float(data.get("confidence") or 0.0)
    return ClassificationResult(
        is_receipt=is_receipt,
        provider_slug=slug,
        provider_id=None,
        layer="2",
        confidence=conf,
        notes=data.get("reasoning"),
    )


def _coerce_json(text: str) -> dict[str, Any]:
    """Find the first JSON object in `text` and parse it tolerantly."""
    if not text:
        return {}
    # quick path
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


# --- Layer 2 -> Provider resolution -----------------------------------------


async def resolve_provider_from_slug(db: AsyncSession, slug: str | None) -> Provider | None:
    if not slug:
        return None
    norm = slug.strip().lower().replace(" ", "-")
    p = await db.scalar(select(Provider).where(Provider.slug == norm))
    if p:
        return p
    # fallback: case-insensitive display_name match
    return await db.scalar(select(Provider).where(Provider.display_name.ilike(slug)))


# --- Orchestration helper --------------------------------------------------


async def classify(db: AsyncSession, inp: ClassificationInput) -> ClassificationResult:
    """Run Layer 1, fall back to Layer 2, signal review if below threshold."""
    res1 = await layer1(db, inp)
    if res1:
        return res1
    res2 = await layer2(inp)
    if res2.is_receipt and res2.confidence >= CONFIDENCE_THRESHOLD:
        prov = await resolve_provider_from_slug(db, res2.provider_slug)
        if prov:
            res2.provider_id = prov.id
        else:
            # known classification but unknown provider — still needs review
            res2.layer = "3"
            res2.notes = (res2.notes or "") + " | provider_unknown"
    elif not res2.is_receipt and res2.confidence >= 0.8:
        # confidently not a receipt — caller may mark as not_a_receipt
        return res2
    else:
        res2.layer = "3"
    return res2
