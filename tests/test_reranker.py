"""
Reranker graceful-degradation tests (Phase 2, RAG hardening spec / ADR
0003). The safety-relevant property under test: a reranker that fails to
load or fails at inference must never crash /chat -- it should fall back
to the pre-rerank fused ordering, same "external dependency gets a
tested fallback" posture as the LLM/embedding clients.
"""
import pytest
from httpx import ASGITransport, AsyncClient

import app.ai.reranker as reranker_module
from app.ai.llm_client import LLMClient
from app.ai.reranker import rerank
from app.config import settings
from app.main import app

AUTH_HEADERS = {"X-API-Key": settings.api_key}

SAMPLE_CHUNKS = [
    {"source": "broker-timeout-runbook.md", "section": "Symptoms", "content": "...", "similarity": 0.99},
    {"source": "broker-timeout-runbook.md", "section": "Overview", "content": "...", "similarity": 0.96},
    {"source": "error-catalogue.md", "section": "EC-014", "content": "...", "similarity": 0.94},
]


def test_rerank_falls_back_when_model_fails_to_load(monkeypatch):
    # Simulates the spec's own named failure mode: "missing file,
    # corrupted cache" -- _get_model()'s internal try/except already
    # returns None on a real load failure; mocking it directly here keeps
    # this test fast and network-free rather than needing to fabricate an
    # actual corrupted model cache on disk.
    monkeypatch.setattr(reranker_module, "_get_model", lambda: None)
    result = rerank("some query", SAMPLE_CHUNKS, top_k=2)
    assert len(result) == 2
    assert [c["source"] for c in result] == ["broker-timeout-runbook.md", "broker-timeout-runbook.md"]
    assert all(c["similarity"] == c["fused_similarity"] for c in result)
    assert all("rerank_score" not in c for c in result)


def test_rerank_falls_back_when_inference_raises(monkeypatch):
    class _RaisingModel:
        def predict(self, pairs):
            raise RuntimeError("simulated inference failure")

    monkeypatch.setattr(reranker_module, "_get_model", lambda: _RaisingModel())
    result = rerank("some query", SAMPLE_CHUNKS, top_k=2)
    assert len(result) == 2
    assert result[0]["source"] == "broker-timeout-runbook.md"
    assert all("rerank_score" not in c for c in result)


def test_rerank_disabled_skips_the_model_entirely(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", False)

    def _should_not_be_called():
        raise AssertionError("reranker model should not be loaded when disabled")

    monkeypatch.setattr(reranker_module, "_get_model", _should_not_be_called)
    result = rerank("some query", SAMPLE_CHUNKS, top_k=1)
    assert len(result) == 1
    assert result[0]["source"] == "broker-timeout-runbook.md"


@pytest.mark.asyncio
async def test_chat_returns_200_when_reranker_unavailable(monkeypatch):
    # The literal scenario from the spec's Phase 2 definition of done: mock
    # the reranker to fail, confirm /chat still returns 200 end-to-end.
    # The LLM call itself is stubbed too (not what this test is about, and
    # a real 7B-model generation call is too slow for the fast unit suite
    # -- see the project's existing convention of not putting live LLM
    # calls in tests/, only in the eval harness).
    monkeypatch.setattr(reranker_module, "_get_model", lambda: None)
    monkeypatch.setattr(
        LLMClient, "generate",
        lambda self, prompt, system="": "Restart the broker pool.\n\nSources: [broker-timeout-runbook.md]",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/chat",
            json={"question": "What does the runbook recommend when Broker session creation repeatedly times out?"},
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "DOCUMENT"
    assert body["escalate"] is False
    assert any("broker-timeout-runbook.md" in s["document"] for s in body["sources"])
