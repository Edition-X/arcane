# Arcane — Agent Guidance

This file tells AI coding agents (Claude Code, Cursor, Copilot Workspace, etc.) how to work with this codebase effectively.

## Project Overview

Arcane is a personal engineering memory system exposed as an MCP (Model Context Protocol) server. It stores decisions, bugs, patterns, and learnings across engineering sessions using SQLite with FTS5 + vector search.

## Architecture

```
src/arcane/
├── cli/            # Click CLI — one module per command group
├── domain/         # Pydantic domain models (Memory, Journey, Artifact…)
├── infra/          # Infrastructure: DB repos, config, search, embeddings, redaction
│   ├── db/         # SQLite schema, MemoryRepo, JourneyRepo, ArtifactRepo, RelationshipRepo
│   └── embeddings/ # Ollama + OpenAI embedding providers
├── mcp_server/     # MCP stdio server + tool handlers
│   └── tools/      # One file per tool group (memory, journey, artifact…)
├── plugins/        # Plugin system (ingestion, intelligence, content)
│   └── builtin/    # Built-in plugins: git, GHA, Linear, CI flakes, velocity, blog, ADR
└── services/       # Business logic: MemoryService, JourneyService, ArtifactService…
```

## Key Conventions

### Dependency Injection
All services receive a `ServiceContainer` (defined in `services/container.py`). Never construct repos or the DB directly outside of `create_container()` or tests. CLI commands must use the `with create_container() as container:` pattern for proper resource cleanup.

### Repository Boundary
All DB read methods return fully deserialized Python objects — tags are `list[str]`, datetimes are strings. Never call `json.loads()` on data returned from a repo method; `_process_row()` in `MemoryRepo` handles this centrally.

### Embedding + Vector Search
Vector search is optional — the system degrades gracefully to FTS if `memories_vec` table is absent or dimensions mismatch. The dimension is stored in `kv_store` and checked on every embed operation. Use `memory_repo.invalidate_vec_cache()` after DDL changes to the vec table.

### Plugin System
Plugins are discovered via Python entry points (`arcane.plugins.ingestion`, `arcane.plugins.intelligence`, `arcane.plugins.content`). Built-in plugins are registered in `pyproject.toml`. Third-party plugins just need to install a package that declares the entry point.

### MCP Server
All MCP tool handlers are synchronous functions wrapped in `anyio.to_thread.run_sync()` to keep the async event loop free. Add new tools in `mcp_server/tools/` and register them in `mcp_server/server.py`.

### Testing
- Unit tests in `tests/unit/` — no DB, no network, mock at boundaries
- Integration tests in `tests/integration/` — real SQLite (`:memory:` or temp file), no network
- CLI tests in `tests/cli/` — patch `create_container` in each CLI sub-module individually
- Plugin tests in `tests/plugins/` — patch `_fetch_all_*` methods on plugin classes

Patch targets use the full dotted path where the name is **used**, not where it is defined:
```python
# Correct
@patch("arcane.cli.memory.create_container")
# Wrong — doesn't intercept the import binding in the module
@patch("arcane.cli._utils.create_container")
```

### Redaction
`infra/redaction.py` runs before any persistence in `MemoryService.save()`. Patterns are compiled at module load. Custom user patterns from config are compiled lazily with malformed ones silently skipped.

## Dev Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pre-commit install

# Run tests
pytest

# Lint + format
ruff check --fix src/ tests/
ruff format src/ tests/

# Type-check
mypy src/arcane
```

## Adding a New Plugin

1. Create `src/arcane/plugins/builtin/my_plugin.py` implementing `IngestionPlugin`, `IntelligencePlugin`, or `ContentPlugin` from `plugins/protocols.py`.
2. Register it in `pyproject.toml` under the appropriate `[project.entry-points]` section.
3. Add tests in `tests/plugins/test_my_plugin.py` mocking network calls.
4. Wire a CLI command in `src/arcane/cli/ingest.py` (or appropriate group).

## Adding a New MCP Tool

1. Create or extend a file in `mcp_server/tools/`.
2. Define a handler function `(args: dict) -> str`.
3. Register it in `mcp_server/server.py` in `_register_tools()` with name, description, and JSON schema.

## Commit Style

Use conventional commits:
- `feat:` new feature
- `fix:` bug fix
- `refactor:` code restructuring, no behaviour change
- `test:` test additions/changes
- `docs:` documentation only
- `chore:` tooling, deps, config
