# ADR 0002: Hybrid retrieval (pgvector + Postgres full-text search, fused via RRF)

## Status
Accepted

## Context
Retrieval was pure vector similarity (pgvector cosine distance) against `nomic-embed-text`
embeddings. Embedding search is strong for semantic matches but can under-rank exact,
low-semantic-content terms — an error code (`EC-014`), a PagerDuty alert name
(`broker_session_create_p99_high`) — because these tokens don't carry much meaning to a
general-purpose embedding model relative to the surrounding prose.

## Decision
Add a second retrieval leg using Postgres's built-in full-text search (`tsvector`/`ts_rank`,
per ADR 0001 — no new datastore, no separate BM25 library) and combine it with the existing
vector leg via Reciprocal Rank Fusion (RRF): each chunk's score is `1/(k + rank)` summed
across whichever leg(s) retrieved it (`k = 60`, the standard constant from the original RRF
paper), normalized to `[0, 1]` by dividing by the max possible score (rank 1 in both legs).

The full-text leg's `tsquery` is built as an OR of the question's lexemes, not the AND
semantics of `plainto_tsquery`/`websearch_to_tsquery` — ANDing every word in a natural-
language question together frequently returns nothing even when one distinctive term (the
error code) is a strong exact match; `ts_rank` still rewards chunks matching more terms.

The fused, normalized score replaces raw cosine similarity as the input to the existing
derived-confidence calculation (`app/ai/rag.py`) — confidence is still a real, explainable,
non-LLM-asserted number, just computed from a different (better) underlying signal.

## Why RRF over a weighted sum
A weighted sum (e.g. `0.5 * cosine_similarity + 0.5 * ts_rank`) requires the two scores to be
on comparable scales, and they aren't: cosine similarity is bounded and roughly uniform,
`ts_rank` is unbounded and depends on document length/term frequency in ways that don't
correspond to cosine similarity's meaning. RRF sidesteps this entirely by fusing on *rank
position*, not raw score — no cross-scale calibration needed, and it's the standard choice
for exactly this two-retriever-fusion problem.

## Why Postgres full-text search over a dedicated BM25 library
Per ADR 0001: one Postgres instance, not a new datastore or service. `tsvector`/`ts_rank`
is Postgres's built-in ranked full-text search — not literally BM25, but the same class of
lexical/keyword-matching signal RRF needs as a complement to the vector leg, without adding
a new dependency or moving data out of the existing database.

## A real, honest finding: measured impact was smaller than expected
Before implementing this, two new eval cases were added (`eval-009`: an EC-code lookup,
`eval-010`: a PagerDuty alert-name lookup) and run against the **pre-hybrid, pure-vector**
code to get a genuine baseline:

- Both passed under pure vector search alone (10/10 eval baseline including the two new
  cases). Direct chunk-level inspection showed the correct chunk already ranked #1 by cosine
  similarity for both (0.82 and 0.91 respectively).
- **This project's sample corpus is only 2 documents**, short and topically coherent — there
  isn't enough near-duplicate or off-topic content for pure embedding search to plausibly
  misrank an exact-term query. The scenario hybrid retrieval is meant to fix (a distinctive
  keyword outranked by something merely semantically similar) needs more/messier documents
  than currently exist to manifest. Phase 5 (golden dataset + corpus expansion) is explicitly
  where this would become a fairer test.
- After implementing hybrid retrieval: still 10/10 (12 unit tests, 10 eval cases), same two
  cases still pass, now ranked #1 with fused scores of 1.0 and 1.0 (both legs agreed on rank
  1). **Saying so honestly rather than overstating an unverified improvement**: on this
  corpus, hybrid retrieval did not change which chunks got cited for these two cases — it
  didn't need to, pure vector search was already correct here.

## A real thing hybrid retrieval DID surface: an RRF scale artifact
Measuring the real fused-score distribution across all eval questions turned up something
that needed fixing before shipping, not just documenting: a chunk retrieved by only **one**
leg at rank 1 always normalizes to **exactly 0.5**, regardless of match quality — a structural
property of the RRF formula (`(1/(k+1)) / (2/(k+1)) = 0.5`), not a quality signal. The
placeholder threshold this ADR started with (`0.5`) would have let the irrelevant
"What is the capital of France?" query (`eval-007`, single vector-leg hit, no full-text match)
clear the bar and route to DOCUMENT instead of ESCALATE — a real regression, caught by
inspecting actual numbers before shipping, not assumed safe from the code. Real genuine
matches (all other eval questions) fused to 0.94–1.0 (multiple legs agreeing). Set
`retrieval_similarity_threshold = 0.6` — comfortably above the 0.5 single-leg-hit artifact,
comfortably below every genuine multi-leg match observed.

## When this decision would change
If the corpus grows large enough that pure vector search demonstrably misranks exact-term
queries (testable once Phase 5 expands `sample_data/runbooks/`), that would be direct
evidence this ADR's mechanism is earning its complexity, not just defensive plumbing. If RRF's
rank-only fusion turns out to lose too much signal (e.g. a very strong single-leg match should
outrank a weak two-leg match), a score-normalized weighted-sum approach would be worth
revisiting — not attempted here since RRF's simplicity was preferred until a concrete case
demands otherwise.

## Consequences
- One new generated column (`runbook_chunks.content_tsv`, `GENERATED ALWAYS AS ... STORED`)
  and one GIN index — maintained by Postgres itself, can't drift out of sync with edited
  content, no app-level indexing code needed.
- `retrieve()`'s candidate pool widened from `k` to `retrieval_candidate_pool` (10) per leg
  before fusion, so downstream latency is bounded by 10-row queries against a GIN/vector
  index, not a full scan — cheap at this corpus size, worth re-measuring if the corpus grows
  by orders of magnitude.
- `retrieval_similarity_threshold`'s meaning changed (fused/normalized RRF score, not raw
  cosine similarity) — anyone tuning it in the future needs to know this, hence the code
  comment in `config.py` and the 0.5-artifact note in `app/ai/rag.py`.
- No schema migration tooling exists in this project (no Alembic) — the new column required
  dropping and recreating `runbook_chunks` locally, the same pattern used for prior
  embedding-model changes. A real deployment with existing indexed data would need an
  actual migration, not a drop/recreate — an honest gap, not fixed here since it's outside
  this phase's scope.
