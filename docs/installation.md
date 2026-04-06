# Installation

## Prerequisites

- **Python 3.11+** — Arcane requires Python 3.11 or later.
- **uv** (recommended) — fast Python package manager. Install from [astral.sh/uv](https://astral.sh/uv).
- **OpenAI API key** (optional) — required only if you want cloud-based semantic search. Local semantic search works out-of-the-box with [Ollama](https://ollama.ai).

---

## Install Arcane

### With uv (recommended)

```bash
uv tool install arcane
```

### With pip

```bash
pip install arcane
```

---

## Verify the install

```bash
arcane --version
```

---

## Initialise

Create the data directory with a default config:

```bash
arcane init
```

This writes `~/.arcane/arcane.db` and `~/.arcane/config.yaml`.

---

## Data directory

By default Arcane stores everything in `~/.arcane/`. Override this with the `ARCANE_HOME` environment variable:

```bash
export ARCANE_HOME=/path/to/custom/dir
arcane init
```

The override can also be persisted via the CLI so you don't need to set the environment variable every session:

```bash
arcane config set-home /path/to/custom/dir
```

---

## Docker

A `docker-compose.yml` is included in the repository root for running Arcane as a long-lived service:

```bash
docker compose up
```

This mounts `~/.arcane` into the container so your data is preserved between restarts.

---

## Next steps

- [Quickstart](quickstart.md) — connect to Claude Code and save your first memory
- [Configuration](configuration.md) — configure embedding providers and context behaviour
