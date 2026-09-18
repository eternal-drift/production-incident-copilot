# ADR 0003: Cross-encoder reranking of the hybrid-retrieval candidate pool

## Status
Accepted

## Context
Hybrid retrieval (ADR 0002) fuses a vector-similarity leg and a full-text leg via Reciprocal
Rank Fusion, scoring each candidate independently of the query (a cosine distance / a
`ts_rank`, computed without ever looking at the two together). A cross-encoder reads the query
and a candidate chunk together and produces a single relevance score for that pair — generally
more precise, but far too slow to run over an entire corpus, which is exactly why it reranks a
small candidate pool rather than replacing retrieval.

## Decision
After RRF fusion produces the candidate pool (`retrieval_candidate_pool = 10`), rerank it with
`cross-encoder/ms-marco-MiniLM-L6-v2` — a small, well-established cross-encoder — down to the
final `k`. Pin the exact model revision (`233902d25c440f23af6f7d6e94d2946bac0bee0a`, not just
the model name) and bake it into the Docker image at build time (`Dockerfile`); the runtime
container sets `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` so a network call at request time
fails loudly instead of silently degrading into a slow/flaky runtime download — this project
already hit a real bug once from exactly that pattern (ChromaDB's default embedder fetching from
Hugging Face at first use, in an earlier version of this codebase).

The cross-encoder's raw score (an unbounded logit, not a `[0, 1]` similarity) is sigmoid-
normalized and averaged with the pre-rerank fused RRF score to produce the final `similarity`
that feeds the existing derived-confidence threshold — per this phase's own design principle, a
new retrieval-quality signal feeds the confidence calculation, it doesn't sit next to it unused.
Each chunk also keeps `fused_similarity` (the pre-rerank score) and `rerank_score` (the raw
logit) for transparency/debugging.

## Why blend rather than replace the confidence signal
Replacing the RRF-fused score outright with the raw cross-encoder logit would mean re-deriving
the confidence threshold from scratch against an unbounded, differently-shaped scale — the exact
kind of recalibration risk ADR 0002 already hit once (the RRF single-leg-hit-always-0.5
artifact). Blending (sigmoid-normalize, then average with the existing fused score) keeps the
combined score on the same intuitive `[0, 1]` scale the threshold was already calibrated
against, and — verified empirically before shipping, not assumed — the existing `0.6` threshold
from ADR 0002 held up without needing to move: every genuine golden-dataset match blended to
0.88–0.99, the irrelevant "capital of France" case stayed at 0.22–0.25, a wide margin on both
sides.

## Real, measured impact — not just "reranking is wired in"
Direct measurement (a script calling `retrieve()` for every golden-dataset question, comparing
the pre-rerank fused order against the post-rerank blended order) found reranking genuinely
changes which chunk gets cited on this corpus, in contrast to ADR 0002's honest finding that
hybrid retrieval alone hadn't yet visibly changed anything on this small 2-document corpus. For
`eval-001`'s question ("What does the runbook recommend when Broker session creation repeatedly
times out?"), the pre-rerank fused top-3 was `{Overview, Symptoms, Recovery}`; the cross-encoder
reordered it to `{Symptoms, Overview, Do not}` — `Recovery` (fused score 0.96, high) scored
strongly negative by the cross-encoder (-4.67) and dropped out of the final three entirely,
replaced by `Do not` (fused 0.95, cross-encoder +1.45). Added as `eval-011` (category
`reranking`), asserting on the actual cited *section*, not just the document — the existing
`expected_source_contains` check alone can't distinguish this, since all candidates here come
from the same file. A new `expected_section_contains` field was added to the eval harness for
this.

## A real, fixed problem this phase surfaced: torch's default Linux wheel bundles ~3.5GB of CUDA
The first working Docker build (before this fix) produced a **5.75GB image** — `du` inside the
running container showed 2.9GB in a `nvidia/` directory alone, plus 652MB in `triton/`, neither
of which this project's plain CPU-only container can use (no GPU exists in this environment,
Docker or otherwise). This is PyPI's default behavior for `torch` on Linux: the standard wheel
declares CUDA runtime packages (`nvidia-cudnn-cu13`, `nvidia-nccl-cu13`, `cuda-toolkit`, etc.) as
hard dependencies regardless of whether a GPU is present. Fixed by scoping `torch` to PyTorch's
own CPU-only wheel index (`download.pytorch.org/whl/cpu`) for Linux specifically, via `uv`'s
`[tool.uv.sources]`/`[[tool.uv.index]]` config in `pyproject.toml`. Result: **1.75GB**, a 4GB
reduction, with zero application-level change — same model, same behavior, verified by rerunning
the full eval suite and the offline-network check (below) after the fix.

Getting the index override to actually take effect required two non-obvious things, found by
inspecting the resolved lockfile directly rather than trusting the config looked right: (1) the
override needed a `marker = "sys_platform == 'linux'"` to only redirect on Linux, since the same
universal lockfile also resolves for macOS/Windows where no CUDA variant exists anyway; (2) the
override had no effect at all until `torch` was also listed as a **direct** project dependency
(not just pulled in transitively via `sentence-transformers`) — `uv`'s source override didn't
bind to a transitive-only package name in this version. Also required switching the Docker
build's dependency install from a plain `pip install -r requirements.txt` to
`uv export --emit-index-url`, since the exported requirements file otherwise drops the
per-package index information pip would need to find the `+cpu`-suffixed version at all.

## Definition-of-done verification performed
- `uv run pytest tests/ -v` — 23/23, including 4 new reranker tests (`tests/test_reranker.py`):
  model-fails-to-load fallback, inference-raises fallback, disabled-via-config skip, and a full
  `/chat` 200-response check with the reranker mocked unavailable (the literal scenario named in
  this phase's spec).
- `uv run python evals/run_evals.py` — 11/11 with reranking enabled (10 prior cases + `eval-011`
  proving reranking changed the cited section).
- **Real offline-network verification**, not assumed from `HF_HUB_OFFLINE=1` alone: added
  `127.0.0.1 huggingface.co` to the running container's `/etc/hosts` (confirmed
  `curl https://huggingface.co` genuinely fails, status `000`), then called `/chat` again and
  confirmed the exact same reranking signature (`Do not` section correctly surfaced) — proving
  the model runs entirely from the build-time-baked cache with zero runtime network dependency.

## When this decision would change
If reranking latency became a real bottleneck (CPU-only cross-encoder inference over a
`retrieval_candidate_pool` of 10 adds real per-request time — not measured precisely here, but
directly proportional to pool size), a smaller pool or a batched/async inference path would be
worth revisiting. If the corpus grows large enough that the candidate pool itself needs to grow
well past 10 to maintain recall, cross-encoder cost scales linearly with it and this would need
re-evaluating against Phase 5's corpus expansion.

## Consequences
- New dependency: `sentence-transformers` (and transitively `torch`, `transformers`). Docker
  image grew from ~570MB (pre-Phase-2) to ~1.75GB — real, non-trivial cost, mitigated but not
  eliminated by the CPU-only-wheel fix above.
- `app/ai/reranker.py` is a new module, following the existing LLM/embedding-client pattern:
  lazy singleton load, never raises, always has a tested fallback.
- `app/ai/rag.py`'s `retrieve()` now returns `fused_similarity`/`rerank_score` alongside
  `similarity` on each chunk — additive, not a breaking change to any existing caller
  (`app/graph/workflow.py`, `app/ai/post_incident.py` only ever read `source`/`section`/
  `content`/`similarity`).
