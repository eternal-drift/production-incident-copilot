"""
POST /chat — the product surface. Runs the LangGraph workflow and
optionally traces the run to Langfuse (Phase 5). Kept optional/guarded
so the endpoint works before Langfuse is wired in (Phase 1-4).

Security controls added per docs/threat-model.md: API key auth (Finding
#1), rate limiting (Finding #4), redaction before observability export
(Finding #5), and a minimal audit log line (Finding #7).
"""
import logging
import re

from fastapi import APIRouter, Depends, Request
from prometheus_client import Counter
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_key
from app.config import settings
from app.database import get_db
from app.graph.workflow import build_graph
from app.rate_limit import limiter
from app.schemas import ChatRequest, ChatResponse, Source

router = APIRouter(tags=["chat"])
logger = logging.getLogger("incident_copilot.audit")

# Phase 4 (RAG hardening spec): request-outcome metrics, exposed on the
# same /metrics endpoint as the HTTP-level ones (prometheus_client uses
# one shared default registry).
DOCUMENT_RESPONSES = Counter(
    "incident_copilot_document_responses_total",
    "DOCUMENT-routed /chat responses, by whether the LLM's own answer included a parseable citation",
    ["has_citation"],
)
CHAT_OUTCOMES = Counter(
    "incident_copilot_chat_outcomes_total",
    "Every /chat outcome by category -- reuses escalate_reason (Phase 3), including the "
    "non-escalating 'llm_unavailable' degraded path, plus 'none' for a clean answer",
    ["reason"],
)

# Best-effort scrub before anything reaches Langfuse/logs -- catches the
# obvious cases (password=..., api_key: ..., AWS-style access keys,
# generic sk-/bearer-style tokens). Not a complete secrets scanner; see
# docs/threat-model.md Finding #5 for the honest scope of this.
_SECRET_PATTERNS = [
    re.compile(r"(password|passwd|pwd)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"),
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
]


def _redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.rate_limit_chat)
async def chat(
    request: Request,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    graph = build_graph(db)

    # Real bug found running this live: `langfuse` was pinned >=4.14.4 in
    # pyproject.toml, a fully OTel-native SDK redesign with NO `.trace()`/
    # `.update()` API -- the code below called methods that don't exist on
    # that version, silently swallowed by `except Exception`, so tracing
    # had been completely non-functional despite settings.langfuse_enabled.
    # The OTel-native client also only speaks to a Langfuse v3 server
    # (needs ClickHouse+Redis); this project runs Langfuse v2 (Postgres-only,
    # see observability/docker-compose.otel.yml) to keep the stack light.
    # Fix: pinned langfuse==2.60.10 to match the v2 server and its
    # `.trace()`-based API, rather than standing up a heavier v3 backend.
    # `get_client()` is ALSO v3-only and doesn't exist in v2 -- instantiate
    # `Langfuse` directly instead, the v2-native way.
    trace = None
    if settings.langfuse_enabled:
        try:
            from langfuse import Langfuse
            langfuse = Langfuse(
                host=settings.langfuse_host,
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
            )
            trace = langfuse.trace(name="incident-copilot-chat", input={"question": _redact(payload.question)})
        except Exception:
            trace = None  # never let observability wiring break the product path

    result = await graph.ainvoke({"question": payload.question})

    if trace:
        try:
            trace.update(output={**result, "answer": _redact(result.get("answer", ""))})
            langfuse.flush()
        except Exception:
            pass

    logger.info(
        "chat_request client=%s decision=%s escalate=%s escalate_reason=%s confidence=%.4f",
        request.client.host if request.client else "unknown",
        result.get("decision"),
        result.get("escalate"),
        result.get("escalate_reason"),
        result.get("confidence", 0.0),
    )

    if result.get("decision") == "DOCUMENT":
        DOCUMENT_RESPONSES.labels(has_citation=str(bool(result.get("has_citation"))).lower()).inc()
    CHAT_OUTCOMES.labels(reason=result.get("escalate_reason") or "none").inc()

    return ChatResponse(
        answer=result.get("answer", ""),
        decision=result.get("decision", "ESCALATE"),
        confidence=result.get("confidence", 0.0),
        sources=[Source(**s) for s in result.get("sources", [])],
        escalate=result.get("escalate", True),
    )
