"""End-to-end harness: the real ``arcane mcp`` server over stdio, as agents run it.

Each test gets its own ``ARCANE_HOME`` and a real git repo with an
``Acme/widget`` remote as the server's working directory, so scope resolves to
org ``acme``, project ``widget``. No embedder is reachable, as in CI, so search
is the FTS path and nothing depends on a local Ollama. Tests that need vectors take
the ``ollama`` fixture, a ``FakeOllama`` serving hashed bag-of-words embeddings.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TypeVar

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, Implementation

T = TypeVar("T")

ARCANE = str(Path(sys.executable).parent / ("arcane.exe" if os.name == "nt" else "arcane"))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=E2E", "-c", "user.email=e2e@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


class Client:
    """A connected MCP session with JSON-decoding helpers for tool calls."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def raw(self, name: str, **arguments: Any) -> CallToolResult:
        return await self.session.call_tool(name, arguments)

    async def call(self, name: str, **arguments: Any) -> Any:
        """Call a tool that must succeed; return its decoded JSON payload."""
        result = await self.raw(name, **arguments)
        text = result.content[0].text  # type: ignore[union-attr]
        assert result.is_error is False, f"{name} failed: {text}"
        return json.loads(text)

    async def error(self, name: str, **arguments: Any) -> str:
        """Call a tool that must fail; return its error message."""
        result = await self.raw(name, **arguments)
        text = result.content[0].text  # type: ignore[union-attr]
        assert result.is_error is True, f"{name} unexpectedly succeeded: {text}"
        try:
            return str(json.loads(text)["error"])
        except (json.JSONDecodeError, KeyError, TypeError):
            return text  # the SDK's own schema validation replies in plain text


@dataclass
class Arcane:
    home: Path
    repo: Path

    def env(self, profile: str) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(
            ARCANE_HOME=str(self.home),
            ARCANE_TOOL_PROFILE=profile,
            ARCANE_OLLAMA_AUTOSTART="0",
            GITHUB_TOKEN="",
            LINEAR_API_KEY="",
        )
        return env

    def run(
        self,
        scenario: Callable[[Client], Awaitable[T]],
        *,
        profile: str = "full",
        client_name: str = "E2E Client",
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> T:
        """Start the server, run *scenario* against it, and shut it down."""

        async def main() -> T:
            params = StdioServerParameters(
                command=ARCANE, args=["mcp"], env={**self.env(profile), **(extra_env or {})}, cwd=str(cwd or self.repo)
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(
                    read, write, client_info=Implementation(name=client_name, version="1.0")
                ) as session:
                    await session.initialize()
                    return await scenario(Client(session))

        return asyncio.run(main())

    def cli(self, *args: str, profile: str = "full", check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run ``arcane <args>`` in the repo against this store."""
        return subprocess.run(
            [ARCANE, *args], cwd=self.repo, env=self.env(profile), capture_output=True, text=True, check=check
        )

    def sql(self, statement: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        """Run SQL against the store directly, for state a test cannot reach through tools."""
        conn = sqlite3.connect(self.home / "index.db", timeout=5)
        try:
            rows = conn.execute(statement, params).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()


def make_arcane(tmp_path: Path) -> Arcane:
    """Make a store and an ``Acme/widget`` repo with two commits under *tmp_path*."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "context:\n  semantic: never\nembedding:\n  base_url: http://127.0.0.1:9\n", encoding="utf-8"
    )
    repo = tmp_path / "widget"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "git@github.com:Acme/widget.git")
    # Words, not digits: artifact search is a prefix match per term, and a
    # digit also prefixes commit SHAs and timestamps, which made which commit
    # ranked first depend on the SHAs git happened to produce.
    for n in ("one", "two"):
        (repo / f"file-{n}.txt").write_text(f"change {n}\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", f"feat: change {n}")
    return Arcane(home=home, repo=repo)


@pytest.fixture
def arcane(tmp_path: Path) -> Arcane:
    return make_arcane(tmp_path)


DIM = 32


def _vector(text: str) -> list[float]:
    """Hash each word into one of DIM buckets: words in common make vectors close, nothing more."""
    vec = [0.0] * DIM
    for word in text.lower().split():
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
    return vec


class FakeOllama:
    """An Ollama embeddings endpoint on a free local port that records every prompt."""

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


def use_fake_ollama(arcane: Arcane, fake: FakeOllama) -> None:
    """Point the store's embedder at *fake*."""
    (arcane.home / "config.yaml").write_text(
        f"context:\n  semantic: never\nembedding:\n  base_url: {fake.url}\n  autostart: false\n", encoding="utf-8"
    )


@pytest.fixture
def ollama(arcane: Arcane) -> Iterator[FakeOllama]:
    """Serve the store's embeddings from a FakeOllama for the length of the test."""
    fake = FakeOllama()
    use_fake_ollama(arcane, fake)
    try:
        yield fake
    finally:
        fake.stop()


def _titles(hits: list[dict[str, Any]]) -> list[str]:
    return [hit["title"] for hit in hits]
