"""
Embedding client: local Ollama (nomic-embed-text) with a deterministic
offline hashing fallback — same graceful-degradation pattern used in the
v1 project, kept because it's a genuinely good pattern, not because it's
familiar. Lets the app run (with reduced retrieval quality, not a crash)
when Ollama isn't available.
"""
import hashlib

import numpy as np
import ollama

from app.config import settings


def _hashing_fallback(text: str, dim: int) -> list[float]:
    vec = np.zeros(dim, dtype=np.float32)
    for token in text.lower().split():
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = np.linalg.norm(vec)
    return (vec / norm if norm > 0 else vec).tolist()


class EmbeddingClient:
    def __init__(self):
        self.client = ollama.Client(host=settings.ollama_host)

    def embed(self, text: str) -> list[float]:
        try:
            resp = self.client.embeddings(model=settings.embedding_model, prompt=text)
            return resp["embedding"]
        except Exception:
            return _hashing_fallback(text, settings.embedding_dim)
