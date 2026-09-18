FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv export --no-dev --format requirements-txt --emit-index-url > requirements.txt
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home appuser
WORKDIR /app
COPY --from=builder /root/.local /home/appuser/.local
COPY app ./app
COPY sample_data ./sample_data
ENV PATH=/home/appuser/.local/bin:$PATH PYTHONUNBUFFERED=1
USER appuser

# Cross-encoder reranker (ADR 0003) -- downloaded and cached into the
# image at BUILD time, pinned to an exact revision, never fetched at
# request time. This project already hit a real bug once from a
# dependency (ChromaDB's default embedder, an earlier version of this
# codebase) fetching a model lazily at runtime -- deliberately not
# repeating that here. HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE below make the
# runtime container use the cache-only path: if the code ever tried to
# hit the network for the model, it would fail loudly instead of
# silently degrading into a slow/flaky runtime download.
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2', revision='233902d25c440f23af6f7d6e94d2946bac0bee0a')"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
