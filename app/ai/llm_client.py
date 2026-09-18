"""
LLM client. Calls LiteLLM's OpenAI-compatible proxy when LITELLM_ENABLED
is true (Phase 2+), otherwise calls Ollama directly (Phase 1 vertical
slice). Isolating this behind one client is exactly why Phase 2 (adding
the gateway) is a same-day change, not a rewrite: this is the one-file
boundary that lets you swap model access strategy without touching the
graph or the API layer.
"""
import ollama
from openai import OpenAI

from app.config import settings


class LLMClient:
    def __init__(self):
        self._use_litellm = settings.litellm_enabled
        if self._use_litellm:
            self._openai_client = OpenAI(base_url=settings.litellm_base_url, api_key=settings.litellm_api_key)
        else:
            self._ollama_client = ollama.Client(host=settings.ollama_host)

    def generate(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if self._use_litellm:
            resp = self._openai_client.chat.completions.create(model=settings.ollama_model, messages=messages)
            return resp.choices[0].message.content
        resp = self._ollama_client.chat(model=settings.ollama_model, messages=messages)
        return resp["message"]["content"]
