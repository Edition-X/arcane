"""Redaction at real MCP/CLI persistence and outbound embedding boundaries."""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.e2e.conftest import ARCANE, Arcane, Client


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("before <redacted>outer<redacted>inner</redacted>tail</redacted> after", "before [REDACTED] after"),
        ("before <redacted>unclosed tail", "before [REDACTED]"),
        ("before <redacted>outer<redacted>inner</redacted>tail", "before [REDACTED]"),
        ("orphan secret</redacted> after", "[REDACTED] after"),
        ("before <REDACTED >hidden</ REDACTED> after", "before [REDACTED] after"),
        ("before <redacted hidden without terminator", "before [REDACTED]"),
        ("before <redacted>hidden</redacted", "before [REDACTED]"),
        ("before <redacted broken <redacted>inner</redacted>tail", "before [REDACTED]"),
        ("secret</redacted broken <unrelated>tail", "[REDACTED]"),
        ('{"password": "JSON secret phrase, with punctuation"}', '{"password": [REDACTED]}'),
        (json.dumps({"secret": 'JSON phrase "quoted", escaped'}), '{"secret": [REDACTED]}'),
        ('{"api_key": "json-api-credential"}', '{"api_key": [REDACTED]}'),
        ("{'client_secret': 'several private words'}", "{'client_secret': [REDACTED]}"),
        ('{"password": "unterminated secret phrase', '{"password": [REDACTED]'),
        ("password=hunter2 and ordinary text", "password=[REDACTED] and ordinary text"),
        ('DB_PASSWORD = "private phrase with spaces"', "DB_PASSWORD = [REDACTED]"),
        ("The password field is useful in forms", "The password field is useful in forms"),
    ],
)
def test_redaction_survives_mcp_db_and_markdown(arcane: Arcane, payload: str, expected: str) -> None:
    async def save(c: Client) -> dict[str, Any]:
        return await c.call(
            "memory_save", title="Boundary check", what=payload, why=payload, impact=payload, details=payload
        )

    saved = arcane.run(save)
    [(what, why, impact)] = arcane.sql("SELECT what, why, impact FROM memories WHERE id = ?", (saved["id"],))
    [(body,)] = arcane.sql("SELECT body FROM memory_details WHERE memory_id = ?", (saved["id"],))
    assert (what, why, impact, body) == (expected,) * 4
    [(indexed,)] = arcane.sql(
        "SELECT what FROM memories_fts WHERE rowid = (SELECT rowid FROM memories WHERE id = ?)", (saved["id"],)
    )
    assert indexed == expected
    markdown = Path(saved["file_path"]).read_text(encoding="utf-8")
    assert expected in markdown
    if payload != expected:
        assert payload not in markdown

    async def read(c: Client) -> dict[str, Any]:
        return await c.call("memory_details", memory_id=saved["id"])

    assert arcane.run(read)["body"] == expected


@pytest.mark.parametrize("key_setting", ["", "  api_key: ''\n", "  api_key: '   '\n"])
def test_openai_requires_explicit_config_key_even_with_environment_key(arcane: Arcane, key_setting: str) -> None:
    async def seed(c: Client) -> None:
        await c.call("memory_save", title="Config check", what="Keep this memory")

    arcane.run(seed)
    (arcane.home / "config.yaml").write_text(
        f"embedding:\n  provider: openai\n  model: text-embedding-3-small\n{key_setting}", encoding="utf-8"
    )
    result = subprocess.run(
        [ARCANE, "reindex"],
        cwd=arcane.repo,
        env={**arcane.env("core"), "OPENAI_API_KEY": "unused-environment-key"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "OpenAI embeddings require embedding.api_key in config.yaml" in result.stderr
    assert arcane.sql("SELECT count(*) FROM memories") == [(1,)]


@pytest.fixture
def live_ollama(arcane: Arcane) -> Iterator[tuple[str, list[str]]]:
    """Record and forward actual requests to Ollama; never fabricate embeddings.

    CI skips this when Ollama or the selected model is unavailable. Override
    ARCANE_TEST_OLLAMA_URL / ARCANE_TEST_OLLAMA_MODEL for a local test backend.
    """
    backend = os.environ.get("ARCANE_TEST_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("ARCANE_TEST_OLLAMA_MODEL", "nomic-embed-text")
    try:
        response = httpx.get(f"{backend}/api/tags", timeout=2)
        response.raise_for_status()
        models = response.json()["models"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        pytest.skip(f"Live Ollama unavailable: {exc}")
    if not any(m["name"].split(":")[0] == model.split(":")[0] for m in models):
        pytest.skip(f"Live Ollama model {model} is not installed")

    prompts: list[str] = []

    class Forwarder(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/api/embeddings":
                prompts.append(json.loads(body)["prompt"])
            response = httpx.post(f"{backend}{self.path}", content=body, timeout=60)
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.content)

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Forwarder)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    (arcane.home / "config.yaml").write_text(
        f"context:\n  semantic: never\nembedding:\n  model: {model}\n  base_url: {base_url}\n  autostart: false\n",
        encoding="utf-8",
    )
    try:
        yield base_url, prompts
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_live_embedding_requests_redact_queries_and_reindex_batches(
    arcane: Arcane, live_ollama: tuple[str, list[str]]
) -> None:
    _, prompts = live_ollama

    async def seed(c: Client) -> None:
        await c.call("memory_save", title="Garden", what="Tulips for customer-48291")
        await c.call("memory_save", title="Recipe", what="Bread flour and yeast")

    arcane.run(seed)
    assert len(prompts) == 2
    assert any("customer-48291" in prompt for prompt in prompts)
    (arcane.home / ".memoryignore").write_text("customer-[0-9]+\n", encoding="utf-8")
    query = (
        'astrophysics customer-48291 {"password": "query private phrase"} '
        "<redacted>outer<redacted>inner</redacted>tail</redacted>"
    )
    prompts.clear()

    async def search(c: Client) -> list[dict[str, Any]]:
        return await c.call("memory_search", query=query)

    results = arcane.run(search)
    assert len(results) == 2
    assert prompts == ['astrophysics [REDACTED] {"password": [REDACTED]} [REDACTED]']
    prompts.clear()
    result = subprocess.run(
        [ARCANE, "reindex"], cwd=arcane.repo, env=arcane.env("core"), capture_output=True, text=True, check=True
    )
    assert "Re-indexed 2 memories" in result.stdout
    assert len(prompts) == 2
    assert all("customer-48291" not in prompt for prompt in prompts)
    assert any("[REDACTED]" in prompt for prompt in prompts)


def test_live_semantic_scores_preserve_l2_order_and_strength(
    arcane: Arcane, live_ollama: tuple[str, list[str]]
) -> None:
    base_url, _ = live_ollama

    async def scenario(c: Client) -> list[dict[str, Any]]:
        for title, what in (
            ("Gardening", "Soil compost roses greenhouse watering"),
            ("Baking", "Sourdough bread oven yeast flour"),
            ("Physics", "Neutrinos electrons photons relativity"),
        ):
            await c.call("memory_save", title=title, what=what)
        return await c.call("memory_search", query="quantum particles", limit=3)

    results = arcane.run(scenario)
    assert len(results) == 3
    assert arcane.sql("SELECT count(*) FROM memories_fts WHERE memories_fts MATCH 'quantum OR particles'") == [(0,)]
    model = os.environ.get("ARCANE_TEST_OLLAMA_MODEL", "nomic-embed-text")
    response = httpx.post(
        f"{base_url}/api/embeddings", json={"model": model, "prompt": "quantum particles"}, timeout=60
    )
    response.raise_for_status()
    query = response.json()["embedding"]
    expected = {}
    # Read the real stored vectors, then independently reproduce sqlite-vec's
    # L2 metric and the documented search fusion weights and scope bonus.
    import sqlite3

    import sqlite_vec

    conn = sqlite3.connect(arcane.home / "index.db")
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        rows = conn.execute(
            "SELECT m.id, v.embedding FROM memories m JOIN memories_vec v ON v.rowid = m.rowid"
        ).fetchall()
    finally:
        conn.close()
    for memory_id, packed in rows:
        vector = struct.unpack(f"{len(packed) // 4}f", packed)
        distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(query, vector, strict=True)))
        expected[memory_id] = 1 / (1 + distance)
    best = max(expected.values())
    assert [r["id"] for r in results] == sorted(expected, key=lambda key: expected[key], reverse=True)
    assert len({r["score"] for r in results}) > 1
    for row in results:
        # The MCP response intentionally rounds displayed scores to 2 places.
        assert row["score"] == round(0.7 * expected[row["id"]] / best + 0.15, 2)
