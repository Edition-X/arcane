# Arcane

> **Unified engineering intelligence** — persistent memory, decision journeys, and knowledge capture for AI-assisted development workflows.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![pre-release beta](https://img.shields.io/badge/status-beta-orange)

Arcane runs as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server, giving Claude Code, Claude Desktop, and other MCP-compatible agents a persistent, searchable knowledge store that survives context window resets and spans every project you work on.

> **Beta software** — APIs and storage formats may change between releases. Pin your version and back up `~/.arcane` before upgrading.

---

## Features

- **Memories** — save and search decisions, bugs, patterns, and learnings with hybrid FTS + vector search
- **Journeys** — track multi-step investigations from problem to exploration to decision to outcome
- **Artifacts** — ingest CI runs, git commits, and Linear tickets as searchable references
- **Relationships** — link any entities (memory to memory, journey to artifact) into a knowledge graph
- **Insights** — detect CI flake patterns and summarise engineering velocity
- **Content generation** — draft blog posts and Architecture Decision Records from your stored knowledge

---

## Install

```bash
# With uv (recommended)
uv tool install arcane

# Or with pip
pip install arcane
```

Then initialise your data directory and connect to your AI agent:

```bash
arcane init
```

[Get started with the Quickstart guide](quickstart.md)
