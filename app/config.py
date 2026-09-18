"""
Centralized settings. sqlite is NOT a valid fallback here the way it was
in the v1 project — pgvector requires real PostgreSQL, so local dev
requires Postgres running (via Docker Compose, or natively). This is a
deliberate trade-off vs. v1's sqlite-first approach: pgvector is the
whole point of this build, so we don't paper over needing Postgres.
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "incident-copilot"
    environment: str = "local"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/incident_copilot"

    # Split credential form, used in Kubernetes so the password comes from a
    # real Secret at runtime instead of being embedded in DATABASE_URL inside
    # a ConfigMap (which isn't RBAC-restricted the way a Secret is -- see
    # docs/threat-model.md Finding #3). When postgres_password is set, it
    # takes priority over database_url below.
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_db: str = "incident_copilot"

    # API key required on /chat and /incidents (docs/threat-model.md Finding
    # #1). "dev-local-key" is a deliberately obvious default for local dev,
    # matching the existing litellm_api_key="sk-local" pattern below -- must
    # be overridden via env/Secret for any real deployment.
    api_key: str = "dev-local-key"
    rate_limit_chat: str = "20/minute"
    rate_limit_incidents: str = "60/minute"

    # MCP (Phase 9, project plan) -- wraps live incident-status lookup as a
    # real MCP server (app/mcp_server.py), consumed via app/ai/mcp_client.py.
    # Disabled by default so local dev / CI don't need a second process
    # running; live_node falls back to a direct DB call either way.
    mcp_enabled: bool = False
    mcp_server_url: str = "http://localhost:8100/mcp"

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if self.postgres_password and self.postgres_host:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self

    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3001"

    # LiteLLM proxy endpoint. If disabled, the app calls Ollama directly —
    # lets Phase 1 (vertical slice) work before Phase 2 wires the gateway in.
    litellm_enabled: bool = False
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = "sk-local"

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768  # nomic-embed-text output size; hashing fallback matches this

    # Grounding thresholds — confidence is DERIVED from these, never
    # asserted by the LLM. See app/ai/rag.py. `retrieval_similarity_threshold`
    # is compared against the normalized RRF-fused score (see ADR 0002), not
    # raw cosine similarity, since hybrid retrieval (Phase 1) replaced the
    # pure-vector confidence input. Recalibrated empirically, not carried
    # over from the pre-hybrid cosine-similarity scale.
    retrieval_similarity_threshold: float = 0.6
    retrieval_min_chunks_for_confidence: int = 1

    # Hybrid retrieval (ADR 0002): candidate pool size fetched from EACH of
    # the vector and full-text legs before Reciprocal Rank Fusion, and the
    # RRF constant (60 is the standard default from the original RRF paper).
    retrieval_candidate_pool: int = 10
    retrieval_rrf_k: int = 60

    # Cross-encoder reranking (ADR 0003). Pinned to an exact model revision
    # (commit hash, not just a name/tag) so the Docker build is
    # reproducible -- baked into the image at build time, never fetched at
    # request time (see Dockerfile). Small, well-established model:
    # prioritizes fast local iteration over marginal quality gains from a
    # larger cross-encoder.
    reranker_enabled: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_model_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


settings = Settings()
