"""
Cross-encoder reranking (Phase 2, RAG hardening spec / ADR 0003). Runs
AFTER hybrid retrieval's RRF fusion (app/ai/rag.py): takes the fused
candidate pool and re-scores each candidate against the query with a
small cross-encoder, which reads the query and chunk together (unlike
the vector/full-text legs, which score each independently) and is
generally more precise at the cost of being too slow to run over a
whole corpus -- exactly why it reranks a small candidate pool rather
than replacing retrieval.

The model is loaded lazily and cached at module level (loading weights
per-request would be far too slow) and pinned to an exact revision
baked into the Docker image at build time (see Dockerfile) -- no
network call happens at request time.

Same "external dependency gets a tested fallback, not a crash" posture
as the LLM/embedding clients: if the model fails to load or inference
fails, log it and fall back to the pre-rerank fused ordering. Never
raises out of `rerank()`.
"""
import logging
import math

from app.config import settings

logger = logging.getLogger("incident_copilot.reranker")

_model = None
_load_attempted = False


def _get_model():
    global _model, _load_attempted
    if _load_attempted:
        return _model
    _load_attempted = True
    try:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(settings.reranker_model, revision=settings.reranker_model_revision)
    except Exception:
        logger.exception("Reranker model failed to load; falling back to pre-rerank ordering")
        _model = None
    return _model


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def rerank(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """`chunks` is the RRF-fused candidate pool, already ordered by fused
    RRF score with each dict carrying `similarity` (see rag.py). Returns
    the top_k chunks re-ordered by cross-encoder score. Each returned
    chunk keeps its original fused score under `fused_similarity` and,
    when reranking actually ran, gets `rerank_score` (raw cross-encoder
    logit) and a blended `similarity` (average of the fused score and the
    sigmoid-normalized rerank score) -- this is what feeds the existing
    derived-confidence threshold (config.py), per this phase's own design
    principle: a new retrieval-quality signal feeds the confidence calc,
    it doesn't get bypassed by an unrelated model's opinion left
    unintegrated. Falls back to the fused ordering's own top_k slice
    (fused_similarity == similarity, no rerank fields) if disabled or if
    the model isn't available or inference fails.
    """
    if not settings.reranker_enabled:
        return [{**c, "fused_similarity": c["similarity"]} for c in chunks[:top_k]]

    model = _get_model()
    if model is None:
        return [{**c, "fused_similarity": c["similarity"]} for c in chunks[:top_k]]

    try:
        pairs = [(query, c["content"]) for c in chunks]
        scores = model.predict(pairs)
    except Exception:
        logger.exception("Reranker inference failed; falling back to pre-rerank ordering")
        return [{**c, "fused_similarity": c["similarity"]} for c in chunks[:top_k]]

    scored = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
    reranked = []
    for chunk, raw_score in scored[:top_k]:
        fused = chunk["similarity"]
        blended = round((fused + _sigmoid(float(raw_score))) / 2, 4)
        reranked.append({
            **chunk,
            "fused_similarity": fused,
            "rerank_score": round(float(raw_score), 4),
            "similarity": blended,
        })
    return reranked
