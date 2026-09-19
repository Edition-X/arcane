"""Ollama embedding provider, with on-demand start of a local Ollama server."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

from arcane.infra.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# Set to 0/false/no/off to stop Arcane from ever starting Ollama (tests, CI).
AUTOSTART_ENV = "ARCANE_OLLAMA_AUTOSTART"
# How long an embed call waits for a server it just started. Ollama is
# usually answering well inside a second.
START_WAIT_SECONDS = 5.0
# A start attempt is not repeated within this window, so a broken install
# costs one failed attempt a minute, not a wait on every save.
START_COOLDOWN_SECONDS = 60.0
DEFAULT_PORT = 11434
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_MACOS_APP = "/Applications/Ollama.app"
_BINARY_FALLBACKS = (
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    f"{_MACOS_APP}/Contents/Resources/ollama",
)

_client: httpx.Client | None = None
_client_lock = threading.Lock()
_start_lock = threading.Lock()
_last_start: float | None = None


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


def autostart_enabled(configured: bool = True) -> bool:
    """Whether Arcane may start Ollama: the config flag, unless the env var turns it off."""
    if os.environ.get(AUTOSTART_ENV, "").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return configured


def is_running(base_url: str, timeout: float = 0.5) -> bool:
    """True when an Ollama server answers at *base_url*. A refused local connection returns at once."""
    try:
        return _http().get(f"{base_url.rstrip('/')}/api/version", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def _local_address(base_url: str) -> tuple[str, int] | None:
    """``(host, port)`` when *base_url* points at this machine; Arcane never starts remote servers."""
    parts = urlsplit(base_url)
    if parts.hostname not in _LOCAL_HOSTS:
        return None
    return parts.hostname, parts.port or DEFAULT_PORT


def _start_command(host: str, port: int) -> tuple[list[str], dict[str, str]] | None:
    """The command that starts Ollama for *host*:*port*, or ``None`` if Ollama is not installed.

    On macOS with Ollama.app on the default port, launch the app in the
    background (no focus change): it owns the server's lifecycle, updates
    and logs. Anywhere else, run a detached ``ollama serve`` bound to the
    configured address.
    """
    if sys.platform == "darwin" and port == DEFAULT_PORT and os.path.isdir(_MACOS_APP):
        return ["open", "-g", "-a", _MACOS_APP], dict(os.environ)
    binary = shutil.which("ollama") or next((p for p in _BINARY_FALLBACKS if os.access(p, os.X_OK)), None)
    if binary is None:
        return None
    bind_host = f"[{host}]" if ":" in host else host
    return [binary, "serve"], {**os.environ, "OLLAMA_HOST": f"{bind_host}:{port}"}


def _spawn(host: str, port: int) -> bool:
    command = _start_command(host, port)
    if command is None:
        logger.debug("Ollama is not installed; cannot start it")
        return False
    argv, env = command
    try:
        subprocess.Popen(
            argv,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # outlives this process and its signals
        )
    except OSError:
        logger.warning("Could not start Ollama with %s", argv[0], exc_info=True)
        return False
    logger.info("Ollama was not running; started it with %s", " ".join(argv))
    return True


def ensure_running(base_url: str, wait: float = 0.0) -> bool:
    """Make sure a local Ollama server is up, starting it if needed.

    Costs one HTTP probe when Ollama is already up. Otherwise starts it (at
    most once per ``START_COOLDOWN_SECONDS`` per process) and polls for up
    to *wait* seconds after the start. A start older than *wait* that never
    came up is not waited on again, so callers fail fast. Returns whether
    the server is answering.
    """
    global _last_start
    if is_running(base_url):
        return True
    address = _local_address(base_url)
    if address is None:
        return False
    with _start_lock:
        now = time.monotonic()
        if _last_start is None or now - _last_start >= START_COOLDOWN_SECONDS:
            if not _spawn(*address):
                return False
            _last_start = now
        started = _last_start
    deadline = started + wait
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if is_running(base_url, timeout=0.2):
            return True
    return False


def start_in_background(base_url: str) -> None:
    """Probe for, and if needed start, Ollama on a daemon thread. Never blocks the caller."""
    threading.Thread(target=ensure_running, args=(base_url,), name="ollama-autostart", daemon=True).start()


class OllamaEmbedding(EmbeddingProvider):
    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        autostart: bool = False,
    ):
        self.model = model
        self.base_url = base_url
        self.autostart = autostart

    def _embed(self, text: str) -> list[float]:
        resp = _http().post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        resp.raise_for_status()
        return list(resp.json()["embedding"])

    def embed(self, text: str) -> list[float]:
        try:
            return self._embed(text)
        except httpx.ConnectError:
            # Nothing listening: start Ollama once and retry, instead of
            # saving this memory without a vector.
            if not self.autostart or not ensure_running(self.base_url, wait=START_WAIT_SECONDS):
                raise
            return self._embed(text)
