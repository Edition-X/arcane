"""Unit tests for the embedding providers, with HTTP mocked at the transport."""

from __future__ import annotations

import json

import httpx
import pytest

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


class _FakeOllama:
    """Stands in for the network and the process launcher around ensure_running."""

    def __init__(self, monkeypatch, *, up_after_spawn: bool = True) -> None:
        self.up = False
        self.spawns: list[tuple[list[str], dict[str, str]]] = []
        self.up_after_spawn = up_after_spawn
        self.clock = 0.0
        monkeypatch.setattr(ollama, "_last_start", None)
        monkeypatch.setattr(ollama, "is_running", lambda base_url, timeout=0.5: self.up)
        monkeypatch.setattr(ollama.time, "monotonic", lambda: self.clock)
        monkeypatch.setattr(ollama.time, "sleep", self._sleep)
        monkeypatch.setattr(ollama.subprocess, "Popen", self._popen)

    def _sleep(self, seconds: float) -> None:
        self.clock += seconds

    def _popen(self, argv, env=None, **_kwargs):
        self.spawns.append((argv, env or {}))
        self.up = self.up_after_spawn


class TestOllamaAutostart:
    def test_running_server_costs_one_probe_and_no_spawn(self, monkeypatch):
        fake = _FakeOllama(monkeypatch)
        fake.up = True

        assert ollama.ensure_running("http://localhost:11434") is True
        assert fake.spawns == []

    def test_starts_the_macos_app_in_the_background(self, monkeypatch):
        fake = _FakeOllama(monkeypatch)
        monkeypatch.setattr(ollama.sys, "platform", "darwin")
        monkeypatch.setattr(ollama.os.path, "isdir", lambda path: path == ollama._MACOS_APP)

        assert ollama.ensure_running("http://localhost:11434", wait=5) is True
        assert fake.spawns[0][0] == ["open", "-g", "-a", ollama._MACOS_APP]

    def test_non_default_port_runs_ollama_serve_bound_to_it(self, monkeypatch):
        fake = _FakeOllama(monkeypatch)
        monkeypatch.setattr(ollama.shutil, "which", lambda name: "/usr/bin/ollama")

        assert ollama.ensure_running("http://127.0.0.1:11500", wait=5) is True
        argv, env = fake.spawns[0]
        assert argv == ["/usr/bin/ollama", "serve"]
        assert env["OLLAMA_HOST"] == "127.0.0.1:11500"

    def test_remote_servers_are_never_started(self, monkeypatch):
        fake = _FakeOllama(monkeypatch)

        assert ollama.ensure_running("http://gpu-box:11434", wait=5) is False
        assert fake.spawns == []

    def test_failed_start_fails_fast_until_cooldown(self, monkeypatch):
        fake = _FakeOllama(monkeypatch, up_after_spawn=False)
        monkeypatch.setattr(ollama.shutil, "which", lambda name: "/usr/bin/ollama")
        monkeypatch.setattr(ollama.sys, "platform", "linux")

        assert ollama.ensure_running("http://localhost:11434", wait=5) is False
        waited = fake.clock
        assert ollama.ensure_running("http://localhost:11434", wait=5) is False
        assert fake.clock == waited  # no second wait inside the cooldown
        assert len(fake.spawns) == 1

        fake.clock += ollama.START_COOLDOWN_SECONDS
        ollama.ensure_running("http://localhost:11434", wait=5)
        assert len(fake.spawns) == 2

    def test_env_var_turns_autostart_off(self, monkeypatch):
        monkeypatch.setenv(ollama.AUTOSTART_ENV, "0")
        assert ollama.autostart_enabled(True) is False
        monkeypatch.delenv(ollama.AUTOSTART_ENV)
        assert ollama.autostart_enabled(True) is True
        assert ollama.autostart_enabled(False) is False

    def test_embed_starts_ollama_and_retries_once(self, monkeypatch):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if len(calls) == 1:
                raise httpx.ConnectError("refused", request=request)
            return httpx.Response(200, json={"embedding": [0.5]})

        monkeypatch.setattr(ollama, "_client", _mock_client(handler))
        started: list[str] = []
        monkeypatch.setattr(ollama, "ensure_running", lambda base_url, wait=0.0: started.append(base_url) or True)
        provider = ollama.OllamaEmbedding(base_url="http://localhost:11434", autostart=True)

        assert provider.embed("x") == [0.5]
        assert started == ["http://localhost:11434"]
        assert calls == ["/api/embeddings", "/api/embeddings"]

    def test_embed_without_autostart_raises(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        monkeypatch.setattr(ollama, "_client", _mock_client(handler))
        monkeypatch.setattr(ollama, "ensure_running", lambda *a, **k: pytest.fail("must not start Ollama"))

        with pytest.raises(httpx.ConnectError):
            ollama.OllamaEmbedding(base_url="http://localhost:11434").embed("x")


class TestStartEmbeddingBackend:
    def _calls(self, monkeypatch) -> list[str]:
        calls: list[str] = []
        monkeypatch.setattr(ollama, "start_in_background", calls.append)
        return calls

    def test_starts_ollama_in_background_when_enabled(self, monkeypatch):
        from arcane.infra.config import ArcaneConfig, EmbeddingConfig
        from arcane.services.container import start_embedding_backend

        calls = self._calls(monkeypatch)
        monkeypatch.delenv(ollama.AUTOSTART_ENV)

        start_embedding_backend(ArcaneConfig(embedding=EmbeddingConfig(base_url="http://localhost:11500")))

        assert calls == ["http://localhost:11500"]

    def test_skips_other_providers_and_disabled_autostart(self, monkeypatch):
        from arcane.infra.config import ArcaneConfig, EmbeddingConfig
        from arcane.services.container import start_embedding_backend

        calls = self._calls(monkeypatch)
        monkeypatch.delenv(ollama.AUTOSTART_ENV)

        start_embedding_backend(ArcaneConfig(embedding=EmbeddingConfig(provider="openai")))
        start_embedding_backend(ArcaneConfig(embedding=EmbeddingConfig(autostart=False)))
        monkeypatch.setenv(ollama.AUTOSTART_ENV, "off")
        start_embedding_backend(ArcaneConfig())

        assert calls == []
