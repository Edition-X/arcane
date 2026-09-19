"""Ollama embedding provider."""

from __future__ import annotations

import threading

import httpx

from arcane.infra.embeddings.base import EmbeddingProvider

_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _http() -> httpx.Client:
    """One pooled client per process: keep-alive to Ollama, and no per-call client setup."""
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(timeout=30.0)
        return _client


def _normalize_model_name(name: str) -> str:
    return name.split(":", 1)[0] if name else ""


def is_model_loaded(model: str, base_url: str, timeout: float = 0.5) -> bool:
    try:
        resp = _http().get(f"{base_url.rstrip('/')}/api/ps", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return False

    target = _normalize_model_name(model)
    for entry in data.get("models") or []:
        name = _normalize_model_name(entry.get("name") or entry.get("model") or "")
        if name == target:
            return True
    return False


class OllamaEmbedding(EmbeddingProvider):
    def __init__(self, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def embed(self, text: str) -> list[float]:
        resp = _http().post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        resp.raise_for_status()
        return list(resp.json()["embedding"])
