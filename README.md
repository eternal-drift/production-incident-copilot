# Incident Copilot

A grounded, evaluated on-call assistant. Retrieves answers from runbooks/error
catalogue (pgvector), checks live incident state when documentation can't
answer the question, and explicitly escalates rather than guessing when
evidence is insufficient. See `docs/adr/0001-single-postgres.md` for the core
architectural trade-off.

**Status of this build:** the Python application, database layer, LangGraph
routing, RAG retrieval, and test/eval suite have been written **and run** in
the build environment, against a real PostgreSQL + pgvector instance — not
just written and assumed to work. Docker, Kubernetes, and Terraform layers
are written correctly against the code but **not executable in this sandbox**
(no Docker daemon, no `kubectl`, no `terraform` binary available here). Each
section below says explicitly which category it's in.

---

## CI

`.github/workflows/ci.yml` runs on every push and pull request: spins up a real
`pgvector/pgvector:pg16` Postgres and a real `ollama/ollama` service, pulls the
same two models (`nomic-embed-text`, `qwen2.5:7b`) used locally, runs
`uv run pytest tests/ -v`, boots the app, then runs the eval harness
(`evals/run_evals.py`) against it. Both gate the build — a test failure or an
eval regression fails the check. Deliberately uses real models rather than the
hashing-embedding fallback: this project's own history found eval results
differ against the fallback, so a green run against it would be a false
signal.

## What's Actually Been Verified

- `uv sync` installs cleanly (109 packages, no conflicts)
- **7/7 pytest tests pass** against a real Postgres 16 + pgvector instance:
  router unit tests (pure logic, no DB) + incident CRUD + health endpoints
- `/chat` tested end-to-end for all three routes:
  - **DOCUMENT**: real pgvector cosine-similarity search retrieved the correct
    runbook sections (confidence 0.69, correctly above the 0.55 threshold)
  - **LIVE**: correctly matched an incident-ID/live-status question and
    queried the incidents table
  - **ESCALATE**: correctly refused an unsafe-action question
    ("restart every production Broker instance") via the deterministic
    keyword guard, independent of retrieval
- Graceful degradation confirmed: with no Ollama running, `/chat` returns a
  clear "LLM unavailable" message instead of a 500, and retrieval/routing
  still work
- The eval harness runs and correctly fails on regressions — **5/7 passed**
  in this environment, and the 2 failures are a real, documented limitation
  (see below), not a harness bug
- Terraform files are syntactically balanced (brace-matched) but **not**
  run through `terraform validate` or `plan` — no Terraform binary was
  fetchable in this sandbox's restricted network

## Known Limitation: Embedding Quality Without Ollama

Two eval cases (`eval-003`, `eval-007`) depend on real semantic embeddings.
Without Ollama's `nomic-embed-text` model running, the app falls back to a
deterministic word-hashing embedding (same resilience pattern as the LLM
client) so retrieval never hard-fails — but hashing embeddings have no real
semantic understanding. In this sandbox that produced two visible effects:
a genuinely out-of-scope question ("What is the capital of France?") got a
false-positive match instead of escalating, and a genuinely in-scope question
fell just under the similarity threshold. **Both are marked
`known_limitation` in `evals/golden_dataset.json`.** Once you run this with
Ollama actually serving `nomic-embed-text`, re-run the eval harness and
expect 7/7 — verify that number yourself rather than assuming it.

---

## Prerequisites

- Docker Desktop / Engine + Compose plugin
- `kubectl` + `kind` or `minikube`
- Terraform >= 1.5
- [Ollama](https://ollama.com)
- [`uv`](https://docs.astral.sh/uv/) (`pip install uv` if you don't have it)

---

## Step 0 — Local run, no Docker (fastest feedback loop)

Requires a local PostgreSQL with the `vector` extension available (Postgres.app,
Homebrew `postgresql@16` + `pgvector`, or just skip to Step 3 and use Docker
Compose instead — this step is optional, Docker Compose is the simpler path
if you don't already have Postgres installed natively).

```bash
cd incident-copilot
uv sync
createdb incident_copilot   # or via your Postgres client of choice
psql incident_copilot -c "CREATE EXTENSION IF NOT EXISTS vector;"

uv run pytest tests/ -v
# Expect: 7 passed

# Pre-download the cross-encoder reranker model (ADR 0003) so it's cached
# locally before starting the app -- Docker builds bake this into the
# image; a non-Docker local run needs this one-time step instead.
uv run python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2', revision='233902d25c440f23af6f7d6e94d2946bac0bee0a')"

uv run uvicorn app.main:app --reload
```

Verify (note: `/chat` and `/incidents` require `X-API-Key` as of the Step 5 threat-model pass —
default `dev-local-key` for local dev, see `.env.example`; `/healthz`/`/readyz` are deliberately
left open for orchestrator health probes):
```bash
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/incidents -H "Content-Type: application/json" -H "X-API-Key: dev-local-key" \
  -d '{"title":"Broker timeout spike","severity":"sev2"}'
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -H "X-API-Key: dev-local-key" \
  -d '{"question":"What does the runbook recommend when Broker session creation repeatedly times out?"}'
```

**Verified in this build:** exactly the above, ran successfully.

---

## Step 1 — Pull local models (Ollama)

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama serve   # if not already running
```

Re-run the eval harness once Ollama is up:
```bash
uv run python evals/run_evals.py --url http://127.0.0.1:8000
```
Expect `7/7 passed` once real embeddings are in play — confirmed 5/7 without
Ollama in this build, with the 2 gaps documented above; verify 7/7 yourself.

---

## Step 2 — Docker Compose (core stack)

```bash
docker compose up --build
```

Brings up: app (`:8000`), Postgres+pgvector (`:5432`), Ollama (`:11434`), and the
MCP server (`:8100`) wrapping live incident-status lookup (see the MCP note
under "Explicitly Not Built" below — it's built, not a stretch goal anymore).

**Not verified here** — no Docker daemon in this sandbox. The `pgvector/pgvector:pg16`
image and env var wiring were cross-checked against `app/config.py`, but this
is your first real checkpoint to debug on your own machine.

### Add the LiteLLM gateway (Phase 2) — verified live
```bash
docker compose --profile gateway up --build
```
Then set `LITELLM_ENABLED=true` and `LITELLM_BASE_URL=http://litellm:4000`
on the `app` service (or via `.env`) and restart. `observability/litellm-config.yaml`
routes `qwen2.5:7b` through Ollama by default — add a second `model_list` entry
to demo swapping in a hosted provider without touching application code.

**Turned this on for real and found a genuine bug**: the official
`ghcr.io/berriai/litellm:main-latest` image crashes with `SIGILL` on this project's ARM64 Docker
environment — the *third* time this exact `cryptography==50.0.0` compiled-extension bug has hit
this project (after `mcp`'s dependency chain and Langfuse's), always the same signature. Fixed
with `observability/litellm.Dockerfile`, a small derived image that bootstraps `pip` (the base
image ships none) and pins `cryptography==43.0.3`. Confirmed the app's `/chat` genuinely routes
through the gateway — not just that it returns 200 — by checking LiteLLM's own request logs
immediately after a real call, then reverted `LITELLM_ENABLED` back to its documented
off-by-default state.

### Add observability (Phase 5): Langfuse + OTel/Prometheus/Grafana — verified live
```bash
docker compose -f docker-compose.yml -f observability/docker-compose.otel.yml \
  --profile observability up --build
```
**One manual step required first:** Langfuse needs its own database on the
shared Postgres instance (`CREATE DATABASE langfuse;` via `psql` against the
`db` container) — this wasn't automated to avoid a fragile init-script
dependency; run it once before starting the `langfuse` service.

Open Grafana at `:3000` (anonymous admin, local-only — never do this in a
real environment) and Langfuse at `:3001`. Generate a few `/chat` requests
and confirm traces appear in both.

**Turned this on for real and found 5 real bugs, all fixed**: a Tempo config field removed in a newer image version; `langfuse/langfuse:latest`
silently becoming v3 (needs ClickHouse — pinned to `:2` instead); a wrong internal port on
`LANGFUSE_HOST`; and, the big one, the Python `langfuse` SDK pin (`>=4.14.4`) being a completely
incompatible major version from what the code was written against — meaning **Langfuse tracing
had been silently non-functional this entire project**, swallowed by the same defensive
`try/except` that was meant to protect the product path from observability failures, not hide a
real bug from ever being noticed. Confirmed working end-to-end after the fix: real Prometheus
metrics, real Tempo traces, and a real Langfuse trace captured from the actual `/chat` code path
with full question/answer/sources/confidence.

**Manual spans + a Grafana dashboard (RAG hardening spec Phase 4)** closed the gap noted above —
every `/chat` trace now includes `rag.vector_search`, `rag.fulltext_search`, `rag.rrf_fusion`,
`rag.rerank`, `llm.generate`, and `citation.verify` spans carrying the real numbers behind each
decision (candidate counts, fused/rerank scores, confidence, citation match), not just HTTP-level
auto-instrumentation. `observability/dashboards/incident-copilot.json` (auto-provisioned) shows
`/chat` p50/p95 latency, citation coverage, and outcomes by failure category — generated from
~28 real varied `/chat` requests and captured to `docs/observability-dashboard.png` as evidence,
not a mockup. Cost-per-request is read from LiteLLM's own built-in cost tracking rather than
bespoke math, and is only a meaningful number once `LITELLM_ENABLED=true` — $0/local on the
default direct-Ollama path.

---

## Step 3 — Local Kubernetes

```bash
docker build -t incident-copilot-app:local .
kind load docker-image incident-copilot-app:local   # or: minikube image load ...

kubectl apply -f k8s/namespace.yaml
cp k8s/secret.yaml.example k8s/secret.yaml   # edit the password first
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/dependencies.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml
```

**Not verified here** — no cluster available in this sandbox. First place to
expect real debugging on your machine (image pull policy, DB connection
timing on first boot).

---

## Step 4 — Terraform (real AWS)

```bash
cd terraform
export TF_VAR_db_password="choose-a-real-password"   # required, no default on purpose
terraform init
terraform plan     # review: S3 bucket, IAM role, RDS PostgreSQL, security group
terraform apply
```

**Not verified here at all** — no Terraform binary was reachable in this
sandbox's network allowlist, so this hasn't even been syntax-checked by the
real tool, only manually brace-matched. **Run `terraform plan` yourself before
`apply`** and read the output carefully — this creates a real RDS instance,
which has an ongoing cost unlike the S3/IAM resources.

```bash
terraform destroy   # when done demoing — RDS is the one resource here worth not leaving running
```

---

## Step 5 — Threat model (Phase 6)

Done as a full dedicated pass, not just this bullet list — see `docs/threat-model.md` for the
complete write-up: assets, trust boundaries, 7 findings each verified live against the running
system (not speculated), severity ratings, and a priority-fix order.

**All 7 findings have since been fixed and re-verified live** (auth, rate limiting, real secrets
handling in Kubernetes, a deterministic prompt-injection guard with a permanent regression test,
observability redaction, and minimal audit logging) — see the doc's per-finding "FIXED" notes for
exactly what changed and how it was verified, including one real deployment mistake caught and
fixed along the way (a Kubernetes manifest applied out of order). The doc is explicit about what's
still genuinely open (full OAuth2/OIDC identity, indirect injection via a compromised runbook
corpus, multi-tenancy) — this pass closed the concrete, tested, highest-priority findings, not
every conceivable one.

---

## System Map

| Component | File(s) | Proves |
|---|---|---|
| FastAPI + Pydantic contract | `app/routers/chat.py`, `app/schemas.py` | API design, strict I/O |
| PostgreSQL + pgvector | `app/models.py`, `docs/adr/0001-*.md` | Grounded retrieval, IaC-relevant trade-off |
| Hybrid retrieval (vector + full-text, RRF) | `app/ai/rag.py`, `docs/adr/0002-*.md` | Retrieval-quality tuning, honest before/after eval reporting |
| Cross-encoder reranking | `app/ai/reranker.py`, `docs/adr/0003-*.md` | Retrieval precision, model baked into the image at build time, real image-size fix (5.75GB → 1.75GB) |
| Derived confidence (not LLM self-report) | `app/ai/rag.py` | AI safety/governance design |
| Citation-match verification | `app/graph/workflow.py` | Catches citation hallucination as a distinct failure category from low-confidence refusal |
| Observability depth (manual spans + Grafana dashboard) | `app/ai/rag.py`, `app/graph/workflow.py`, `observability/dashboards/` | A trace explains *why* an answer got its confidence, not just that it happened; real dashboard export in `docs/observability-dashboard.png` |
| LangGraph routing | `app/graph/workflow.py` | Agentic workflow, deterministic boundaries |
| LiteLLM-ready client | `app/ai/llm_client.py` | Model gateway pattern |
| Eval harness w/ documented limitations | `evals/` | LLMOps, honest quality reporting — 33 cases across 11 sample documents as of the RAG hardening spec's Phase 5 |
| Docker/K8s/Terraform | `Dockerfile`, `k8s/`, `terraform/` | Platform/cloud fluency |
| MCP (real server + client) | `app/mcp_server.py`, `app/ai/mcp_client.py` | Protocol integration, graceful degradation |
| Post-incident review draft | `app/ai/post_incident.py`, `POST /incidents/{id}/review` | AI governance: draft-only, human-approved output |

---

## Explicitly Not Built (see the project plan for why)

React/UI, Backstage, production EKS, service mesh, multi-agent architecture,
multiple vector databases.

**MCP (Phase 9) — now built**, scoped exactly as the plan specifies: the live
incident-status capability is wrapped as a real MCP server
(`app/mcp_server.py`, `docker-compose.yml`'s `mcp-server` service) and
consumed by the app over the actual protocol (`app/ai/mcp_client.py`), with
a graceful fallback to the direct DB call if the server is disabled or
unreachable — same resilience pattern as the LLM/embedding clients. Not
extended into the Kubernetes manifests — out of scope for the plan's stated
"wrap it and consume it through the application" bar.

**Post-incident review (Phase 8) — now built**: `POST /incidents/{id}/review`
generates a structured draft (Incident Summary, Impact, Timeline, Detection,
Root Cause/Contributing Factors, Resolution, What Worked/Did Not, Runbook
Gap, Corrective Actions, Suggested Runbook Update) grounded in the incident
record and retrieved runbook context, always returned with an explicit
DRAFT disclaimer — never presented as an authoritative RCA. **Live testing
found a real limitation worth knowing about**: despite an explicit
system-prompt instruction not to invent details, the model fabricated a
plausible-looking PagerDuty alert name and precise clock timestamps that
were never in the input. The disclaimer was strengthened to name this
concretely (`app/ai/post_incident.py`'s `DRAFT_DISCLAIMER`) rather than
claiming the instruction fully worked — this is exactly the kind of
generated-misinformation risk the phase's own "must be clearly marked for
human review" requirement exists for.
