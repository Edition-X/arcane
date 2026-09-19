"""Unit tests for the embedding providers, with HTTP mocked at the transport."""

from __future__ import annotations

import json

import httpx

from arcane.infra.embeddings import ollama
from arcane.infra.embeddings.openai_embed import OpenAIEmbedding


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestOllama:
    def test_embed_posts_prompt_and_reuses_one_client(self, monkeypatch):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"embedding": [0.1, 0.2]})

        monkeypatch.setattr(ollama, "_client", _mock_client(handler))
        provider = ollama.OllamaEmbedding(model="nomic-embed-text", base_url="http://ollama.test")

        assert provider.embed("a") == [0.1, 0.2]
        assert provider.embed("b") == [0.1, 0.2]
        assert seen == [{"model": "nomic-embed-text", "prompt": "a"}, {"model": "nomic-embed-text", "prompt": "b"}]

    def test_is_model_loaded_ignores_tags(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ps"
            return httpx.Response(200, json={"models": [{"name": "nomic-embed-text:latest"}]})

        monkeypatch.setattr(ollama, "_client", _mock_client(handler))

        assert ollama.is_model_loaded("nomic-embed-text", "http://ollama.test/") is True
        assert ollama.is_model_loaded("other-model", "http://ollama.test") is False

    def test_is_model_loaded_is_false_when_unreachable(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        monkeypatch.setattr(ollama, "_client", _mock_client(handler))

        assert ollama.is_model_loaded("nomic-embed-text", "http://ollama.test") is False


class TestOpenAI:
    def test_embed_batch_keeps_input_order(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer key"
            inputs = json.loads(request.content)["input"]
            data = [{"index": i, "embedding": [float(i)]} for i in range(len(inputs))]
            return httpx.Response(200, json={"data": list(reversed(data))})

        provider = OpenAIEmbedding(api_key="key")
        client = _mock_client(handler)
        client.headers["Authorization"] = "Bearer key"
        monkeypatch.setattr(provider, "_client", client)

        assert provider.embed_batch(["a", "b", "c"]) == [[0.0], [1.0], [2.0]]
        assert provider.embed("a") == [0.0]
