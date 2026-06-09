"""Model Gateway (pipeline layer 0).

Internal abstraction over the LLM provider (AvalAI, OpenAI-compatible) so each
pipeline layer picks its own model and no code is locked to a vendor. With no API
key a deterministic NullModel is returned, so the whole pipeline is exercisable
in dev/CI without spend — same NullProvider pattern as the platform's SMS/billing.
"""

from typing import Optional

import httpx

from .config import LAYER_MODELS, settings


class NullModel:
    """Deterministic stub used when no API key is configured."""

    name = "null"

    def complete(self, messages, *, max_tokens: int = 512, temperature: float = 0.0) -> str:
        # echo a stable marker so callers/tests can assert without spend
        last = messages[-1]["content"] if messages else ""
        return f"[[null-model:{len(last)}chars]]"


class AvalAIModel:
    name = "avalai"

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def complete(self, messages, *, max_tokens: int = 512, temperature: float = 0.0) -> str:
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model, "messages": messages,
                "max_tokens": max_tokens, "temperature": temperature,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def get_model(layer: str, override_model: Optional[str] = None):
    """Return the model client for a pipeline layer (model tiering)."""
    model_name = override_model or LAYER_MODELS.get(layer, settings.model_extraction)
    if not settings.avalai_api_key:
        return NullModel()
    return AvalAIModel(model_name, settings.avalai_api_key, settings.avalai_base_url)
