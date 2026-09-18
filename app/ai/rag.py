"""
Grounded retrieval: pgvector + Postgres full-text search, fused (RRF) and
reranked (cross-encoder). This is the module the whole safety story
depends on: `confidence` is DERIVED from retrieval quality, never from
the LLM asserting a number about itself. See ADR 0001 for the
single-Postgres choice, ADR 0002 for hybrid retrieval, ADR 0003 for
reranking, and config.py for the threshold values.
"""
import os
import re
import uuid

from opentelemetry import trace
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingClient
from app.ai.reranker import rerank
from app.config import settings
from app.models import RunbookChunk

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sample_data", "runbooks")

# Manual spans (Phase 4, RAG hardening spec) -- closes the self-documented
# gap that only HTTP-level auto-instrumented spans existed, so a "why is
# this slow / why did it get this confidence" question couldn't be
# answered from a single trace. A no-op tracer is used automatically when
# OTel isn't enabled (settings.otel_enabled=False), so these calls are
# always safe -- no conditional needed here.
tracer = trace.get_tracer("incident_copilot.rag")


def _chunk_text(content: str, chunk_size: int = 500, overlap: int = 60) -> list[str]:
    chunks = []
    start = 0
    while start < len(content):
        end = start + chunk_size
        chunks.append(content[start:end])
        start = end - overlap
    return [c.strip() for c in chunks if c.strip()]


async def index_runbooks(db: AsyncSession) -> int:
    """Idempotent-ish reindex: skips if chunks already exist."""
    existing = await db.execute(select(RunbookChunk.id).limit(1))
    if existing.scalar_one_or_none() is not None:
        return 0

    embedder = EmbeddingClient()
    count = 0
    for fname in os.listdir(DOCS_DIR):
        path = os.path.join(DOCS_DIR, fname)
        with open(path) as f:
            content = f.read()
        # naive section split on markdown headers, falls back to whole doc
        sections = content.split("\n## ")
        for i, section in enumerate(sections):
            section_title = section.split("\n")[0].strip("# ") if i > 0 else "Overview"
            for chunk in _chunk_text(section):
                embedding = embedder.embed(chunk)
                db.add(RunbookChunk(
                    source_document=fname,
                    section=section_title,
                    content=chunk,
                    embedding=embedding,
                ))
                count += 1
    await db.commit()
    return count


def _tsquery_terms(query: str) -> str:
    """OR-joined lexemes for the full-text leg -- deliberately OR, not the
    AND semantics of plainto_tsquery/websearch_to_tsquery. The vector leg
    already handles semantic recall; the full-text leg's job is precision
    on exact terms (error codes, alert names), and ANDing every word in a
    natural-language question together would frequently return nothing
    even when one distinctive term is a strong exact match. `ts_rank`
    still rewards chunks that match more of the terms."""
    words = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-]*", query.lower())
    return " | ".join(words)


async def _fulltext_search(db: AsyncSession, query: str, limit: int) -> list[tuple[RunbookChunk, float]]:
    terms = _tsquery_terms(query)
    if not terms:
        return []
    tsquery = func.to_tsquery("english", terms)
    stmt = (
        select(RunbookChunk, func.ts_rank(RunbookChunk.content_tsv, tsquery).label("rank"))
        .where(RunbookChunk.content_tsv.op("@@")(tsquery))
        .order_by(text("rank DESC"))
        .limit(limit)
    )
    try:
        result = await db.execute(stmt)
        return result.all()
    except Exception:
        # to_tsquery can reject pathological input (e.g. an operator-only
        # token); degrade to vector-only rather than fail the whole
        # request, same "external dependency gets a tested fallback"
        # posture as the embedding/LLM clients. Roll back so the failed
        # statement doesn't poison the rest of this request's transaction.
        await db.rollback()
        return []


def _reciprocal_rank_fusion(
    vector_rows: list[tuple[RunbookChunk, float]],
    fulltext_rows: list[tuple[RunbookChunk, float]],
    rrf_k: int,
) -> list[tuple[RunbookChunk, float]]:
    """Rank-based fusion (not score-based): a chunk's contribution from
    each leg is 1/(rrf_k + its rank in that leg's result list), summed
    across legs. Rank-based avoids having to reconcile cosine similarity
    and ts_rank's un-comparable scales. Normalized to [0, 1] by dividing
    by the max possible score (rank 1 in both legs), so the result stays
    on the same intuitive scale the pre-hybrid cosine threshold used."""
    scores: dict[str, float] = {}
    chunks_by_id: dict[str, RunbookChunk] = {}
    for rows in (vector_rows, fulltext_rows):
        for rank, (chunk, _score) in enumerate(rows, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + rank)
            chunks_by_id[chunk.id] = chunk

    # Note: a chunk found by exactly one leg at rank 1 always normalizes to
    # precisely 0.5, regardless of how strong that single-leg match was --
    # a structural property of RRF, not a quality signal. The confidence
    # threshold (config.py) must sit meaningfully above 0.5, otherwise
    # every single-leg top hit (including an irrelevant one, if the vector
    # leg alone happens to rank something first) would clear it.
    max_possible = 2.0 / (rrf_k + 1)
    fused = [(chunks_by_id[cid], score / max_possible) for cid, score in scores.items()]
    fused.sort(key=lambda pair: pair[1], reverse=True)
    return fused


async def retrieve(db: AsyncSession, query: str, k: int = 3) -> dict:
    """
    Returns retrieved chunks PLUS a derived confidence score and an
    explicit sufficient_evidence boolean. Callers (the LangGraph router
    and the /chat endpoint) use sufficient_evidence to decide whether to
    escalate — this is application logic, not a prompt instruction, per
    the plan's explicit requirement.

    Retrieval is hybrid (ADR 0002): a vector-similarity leg (pgvector
    cosine distance) and a full-text leg (Postgres tsvector/ts_rank) each
    contribute a candidate pool, fused via Reciprocal Rank Fusion. The
    fused candidate pool is then reranked by a cross-encoder (ADR 0003,
    app/ai/reranker.py) down to the final k. The resulting blended score
    is what `similarity`/`confidence` mean below — no longer raw cosine
    similarity, and no longer just the fused RRF score either.
    """
    with tracer.start_as_current_span("rag.retrieve") as retrieve_span:
        await index_runbooks(db)

        embedder = EmbeddingClient()
        query_embedding = embedder.embed(query)
        pool = settings.retrieval_candidate_pool

        with tracer.start_as_current_span("rag.vector_search") as span:
            vector_stmt = (
                select(
                    RunbookChunk,
                    RunbookChunk.embedding.cosine_distance(query_embedding).label("distance"),
                )
                .order_by(text("distance"))
                .limit(pool)
            )
            vector_rows = (await db.execute(vector_stmt)).all()
            span.set_attribute("rag.vector.candidate_count", len(vector_rows))

        with tracer.start_as_current_span("rag.fulltext_search") as span:
            fulltext_rows = await _fulltext_search(db, query, pool)
            span.set_attribute("rag.fulltext.candidate_count", len(fulltext_rows))

        with tracer.start_as_current_span("rag.rrf_fusion") as span:
            fused = _reciprocal_rank_fusion(vector_rows, fulltext_rows, settings.retrieval_rrf_k)
            span.set_attribute("rag.fusion.candidate_count", len(fused))
            if fused:
                span.set_attribute("rag.fusion.top_score", fused[0][1])

        # The full candidate pool (not just the top k) goes to the reranker --
        # a candidate the fusion step ranked #5 could plausibly outrank #1
        # once the cross-encoder reads the actual query+chunk pair together.
        candidates = [
            {
                "source": chunk.source_document,
                "section": chunk.section,
                "content": chunk.content,
                "similarity": round(float(score), 4),
            }
            for chunk, score in fused
        ]

        with tracer.start_as_current_span("rag.rerank") as span:
            span.set_attribute("rag.rerank.enabled", settings.reranker_enabled)
            chunks = rerank(query, candidates, k)
            if chunks:
                top = chunks[0]
                span.set_attribute("rag.rerank.top_fused_similarity", top.get("fused_similarity", top["similarity"]))
                if "rerank_score" in top:
                    span.set_attribute("rag.rerank.top_rerank_score", top["rerank_score"])

        strong_chunks = [c for c in chunks if c["similarity"] >= settings.retrieval_similarity_threshold]
        sufficient_evidence = len(strong_chunks) >= settings.retrieval_min_chunks_for_confidence

        # Confidence = best fused score among retrieved chunks, floored at 0
        # if nothing cleared the threshold. Simple, explainable, and
        # traceable back to a real number rather than an LLM's self-report.
        confidence = round(max((c["similarity"] for c in strong_chunks), default=0.0), 4)

        retrieve_span.set_attribute("rag.confidence", confidence)
        retrieve_span.set_attribute("rag.sufficient_evidence", sufficient_evidence)

        return {
            "chunks": chunks,
            "strong_chunks": strong_chunks,
            "sufficient_evidence": sufficient_evidence,
            "confidence": confidence,
        }
