"""E2E: memory details are searchable, and every search runs keyword and vector search.

The real ``arcane mcp`` server and CLI run against a temp store. Only Ollama is
faked: a local HTTP server that turns text into a hashed bag-of-words vector,
records every prompt, and can be made slow or stopped.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from tests.e2e.conftest import ARCANE, Arcane, Client

DIM = 32


def _vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in text.lower().split():
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
    return vec


class FakeOllama:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.delay = 0.0
        self.max_chars: int | None = None  # longer prompts get Ollama's context-length error
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                outer.prompts.append(body["prompt"])
                if outer.max_chars is not None and len(body["prompt"]) > outer.max_chars:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error":"the input length exceeds the context length"}')
                    return
                if outer.delay:
                    time.sleep(outer.delay)
                payload = json.dumps({"embedding": _vector(body["prompt"])}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:  # the client gave up waiting
                    pass

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ollama(arcane: Arcane) -> Iterator[FakeOllama]:
    fake = FakeOllama()
    (arcane.home / "config.yaml").write_text(
        f"context:\n  semantic: never\nembedding:\n  base_url: {fake.url}\n  autostart: false\n", encoding="utf-8"
    )
    try:
        yield fake
    finally:
        fake.stop()


def _titles(hits: list[dict[str, Any]]) -> list[str]:
    return [hit["title"] for hit in hits]


def test_words_only_in_details_find_the_memory(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        await c.call("memory_save", title="Cache layer", what="Added a cache", details="Options: redis, memcached")
        await c.call("memory_save", title="Queue layer", what="Added a queue", details="Options: sqs, rabbitmq")
        out: dict[str, Any] = {"found": await c.call("memory_search", query="rabbitmq")}
        await c.call("memory_update", memory_id=(out["found"][0]["id"]), details_append="Later we tried zeromq")
        out["appended"] = await c.call("memory_search", query="zeromq")
        # A same-titled save folds into the memory and appends its details.
        await c.call("memory_save", title="Cache layer", what="Added a cache", details="Revisited with hazelcast")
        out["merged"] = await c.call("memory_search", query="hazelcast")
        out["merged_old"] = await c.call("memory_search", query="memcached")
        await c.call("memory_delete", memory_id=out["found"][0]["id"])
        out["deleted"] = await c.call("memory_search", query="rabbitmq zeromq")
        return out

    out = arcane.run(scenario)
    assert _titles(out["found"]) == ["Queue layer"]
    assert _titles(out["appended"]) == ["Queue layer"]
    assert _titles(out["merged"]) == ["Cache layer"]
    assert _titles(out["merged_old"]) == ["Cache layer"]
    assert out["deleted"] == [] or out["deleted"]["results"] == []


def test_title_and_why_matches_outrank_a_long_details_body(arcane: Arcane) -> None:
    async def scenario(c: Client) -> list[dict[str, Any]]:
        # Enough other memories for the word to carry weight, as in a real store.
        for n in range(10):
            await c.call("memory_save", title=f"Other {n}", what="Something else", details="words " * 30)
        await c.call("memory_save", title="Notes", what="Long write-up", details=("filler words " * 80 + "marmot ") * 5)
        await c.call("memory_save", title="Reason", what="Short", why="The marmot is the cause")
        await c.call("memory_save", title="Marmot burrows", what="Short")
        return await c.call("memory_search", query="marmot", limit=3)

    out = arcane.run(scenario)
    assert _titles(out) == ["Marmot burrows", "Reason", "Notes"]


def _fts_rows(arcane: Arcane) -> list[tuple[Any, ...]]:
    return arcane.sql("SELECT rowid, title, details FROM memories_fts ORDER BY rowid")


def test_upgrade_indexes_details_and_running_it_twice_changes_nothing(arcane: Arcane) -> None:
    async def seed(c: Client) -> None:
        await c.call("memory_save", title="Cache layer", what="Added a cache", details="Options: redis, memcached")
        await c.call("memory_save", title="Queue layer", what="Added a queue")

    arcane.run(seed)
    # Put the store back as 0.2.2 left it: an external-content index of the memory columns only.
    conn = sqlite3.connect(arcane.home / "index.db")
    conn.executescript("""
        DROP TRIGGER memories_ai; DROP TRIGGER memories_au; DROP TRIGGER memories_ad;
        DROP TRIGGER memory_details_ai; DROP TRIGGER memory_details_au; DROP TRIGGER memory_details_ad;
        DROP TABLE memories_fts;
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            title, what, why, impact, tags, category, project, source,
            content='memories', content_rowid='rowid', tokenize='porter unicode61'
        );
        INSERT INTO memories_fts(memories_fts) VALUES ('rebuild');
    """)
    conn.close()

    async def search(c: Client) -> list[dict[str, Any]]:
        return await c.call("memory_search", query="memcached")

    assert _titles(arcane.run(search)) == ["Cache layer"]
    first = _fts_rows(arcane)
    assert first == [(1, "Cache layer", "Options: redis, memcached"), (2, "Queue layer", None)]
    triggers = arcane.sql("SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name")

    assert _titles(arcane.run(search)) == ["Cache layer"]
    assert _fts_rows(arcane) == first
    assert arcane.sql("SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name") == triggers


def test_every_search_embeds_the_query_once(arcane: Arcane, ollama: FakeOllama) -> None:
    async def scenario(c: Client) -> list[Any]:
        await c.call("memory_save", title="Cache layer", what="Added a cache for sessions")
        await c.call("memory_save", title="Queue layer", what="Added a queue for jobs")
        ollama.prompts.clear()
        out = []
        for query in ("cache", "queue jobs", "cache sessions queue jobs and more words"):
            before = len(ollama.prompts)
            out.append(await c.call("memory_search", query=query))
            assert ollama.prompts[before:] == [query]
        return out

    # Three keyword matches or none, the embedding model is asked every time.
    assert len(arcane.run(scenario)) == 3


def test_search_with_the_provider_down_returns_keyword_results(arcane: Arcane, ollama: FakeOllama) -> None:
    async def seed(c: Client) -> None:
        await c.call("memory_save", title="Cache layer", what="Added a cache", details="Options: redis")

    arcane.run(seed)
    ollama.stop()

    async def search(c: Client) -> list[dict[str, Any]]:
        return await c.call("memory_search", query="redis")

    assert _titles(arcane.run(search)) == ["Cache layer"]


def test_a_slow_provider_costs_one_timeout_not_one_per_search(arcane: Arcane, ollama: FakeOllama) -> None:
    async def seed(c: Client) -> None:
        await c.call("memory_save", title="Cache layer", what="Added a cache", details="Options: redis")

    arcane.run(seed)
    ollama.prompts.clear()
    ollama.delay = 5.0

    async def scenario(c: Client) -> list[float]:
        timings = []
        for _ in range(2):
            start = time.monotonic()
            hits = await c.call("memory_search", query="redis")
            timings.append(time.monotonic() - start)
            assert _titles(hits) == ["Cache layer"]
        return timings

    first, second = arcane.run(scenario)
    assert first < 4.5  # the 2 s query timeout, not the 5 s the server takes
    assert second < 1.0
    assert ollama.prompts == ["redis"]


def test_reindex_embeds_details_up_to_the_cut(arcane: Arcane, ollama: FakeOllama) -> None:
    body = "early-marker " + "filler " * 1200 + "late-marker"

    async def seed(c: Client) -> None:
        await c.call("memory_save", title="Cache layer", what="Added a cache", details="Options: redis, memcached")
        await c.call("memory_save", title="Long write-up", what="Short", details=body)
        await c.call("memory_save", title="No details", what="Plain")

    arcane.run(seed)
    ollama.prompts.clear()
    result = subprocess.run(
        [ARCANE, "reindex"], cwd=arcane.repo, env=arcane.env("core"), capture_output=True, text=True, check=True
    )
    assert "Re-indexed 3 memories" in result.stdout
    assert len(ollama.prompts) == 3
    by_title = {p.split(" ", 1)[0]: p for p in ollama.prompts}
    assert "memcached" in by_title["Cache"]
    assert "early-marker" in by_title["Long"]
    assert "late-marker" not in by_title["Long"]
    assert by_title["No"].split() == ["No", "details", "Plain"]


def test_a_text_too_long_for_the_model_is_cut_and_still_embedded(arcane: Arcane, ollama: FakeOllama) -> None:
    ollama.max_chars = 500

    async def scenario(c: Client) -> list[dict[str, Any]]:
        await c.call("memory_save", title="Long what", what="word " * 400)
        return await c.call("memory_search", query="word")

    assert _titles(arcane.run(scenario)) == ["Long what"]
    assert len(ollama.prompts) > 2  # the save was refused and retried, then the search embedded its query
    assert arcane.sql("SELECT count(*) FROM memories_vec_rowids") == [(1,)]


def test_details_only_matches_count_as_local_so_the_search_does_not_widen(arcane: Arcane) -> None:
    async def scenario(c: Client) -> list[dict[str, Any]]:
        for n in ("one", "two", "three"):
            await c.call(
                "memory_save",
                title=f"Burrow survey {n}",
                what="Counted burrows",
                details="Notes on marsupial habitat",
                project="widget",
                org="acme",
            )
        await c.call("memory_save", title="Marsupial habitat", what="Sibling note", project="gadget", org="acme")
        return await c.call("memory_search", query="marsupial habitat")

    hits = arcane.run(scenario)
    # Three local memories hold the words in their details, so the project is not thin and the sibling stays out.
    assert {hit["project"] for hit in hits} == {"widget"}
    assert len(hits) == 3


def test_a_widened_search_keeps_a_local_keyword_hit_in_the_top_results(arcane: Arcane, ollama: FakeOllama) -> None:
    async def scenario(c: Client) -> list[dict[str, Any]]:
        # The phrase sits in a long details body, so the memory's vector is far from the query.
        await c.call(
            "memory_save",
            title="Rollout plan",
            what="Staged the deploy",
            details="Options considered: quokka lattice. " + "filler text about other things " * 60,
            project="widget",
            org="acme",
        )
        # Sibling notes share no word with the query, at a spread of distances from it.
        for n in range(1, 21):
            await c.call("memory_save", title=f"Sibling {n}", what="item " * n, project="gadget", org="acme")
        return await c.call("memory_search", query="quokka lattice", limit=5, project="widget", org="acme")

    hits = arcane.run(scenario)
    # One local match, so the search widens to the org. The exact keyword hit in
    # the project must not fall below vector-only neighbours from another project.
    assert "Rollout plan" in _titles(hits)
