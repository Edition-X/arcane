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
│   └── builtin/    # Built-in plugins: git, GHA, Linear, velocity, blog, ADR
└── services/       # Business logic: MemoryService, JourneyService, ArtifactService…
```

## Key Conventions

### Dependency Injection
All services receive a `ServiceContainer` (defined in `services/container.py`). Never construct repos or the DB directly outside of `create_container()` or tests. CLI commands must use the `with create_container() as container:` pattern for proper resource cleanup.

### Repository Boundary
All DB read methods return fully deserialized Python objects — tags are `list[str]`, datetimes are strings. Never call `json.loads()` on data returned from a repo method; `_process_row()` in `MemoryRepo` handles this centrally.

### Embedding + Vector Search
Vector search is optional — the system degrades gracefully to FTS if `memories_vec` table is absent or dimensions mismatch. The dimension is stored in the `meta` table and checked on every embed operation. Use `memory_repo.invalidate_vec_cache()` after DDL changes to the vec table. Never `ALTER TABLE ... RENAME` a vec0 table: its shadow tables keep the old name and the renamed table stops working — drop and recreate it inside one transaction instead.

### Plugin System
Plugins are discovered via Python entry points (`arcane.plugins.ingestion`, `arcane.plugins.intelligence`, `arcane.plugins.content`). Built-in plugins are registered in `pyproject.toml`. Third-party plugins just need to install a package that declares the entry point.

### MCP Server
All MCP tool handlers are synchronous functions wrapped in `anyio.to_thread.run_sync()` to keep the async event loop free. Add new tools in `mcp_server/tools/` and register them in `mcp_server/server.py`.

### Testing

New tests are end-to-end: they drive a real entry point against a real store. Do not add mocked unit tests.

- E2E tests in `tests/e2e/` — the real `arcane mcp` server over stdio, a temp `ARCANE_HOME`, and a real git repo as its working directory. Every MCP behaviour is tested here; `tests/e2e/conftest.py` has the harness (`arcane.run(scenario)`, `Client.call`/`Client.error`, `arcane.sql`). No embedder is reachable, as in CI.
- CLI tests in `tests/cli/` — prefer `CliRunner` with `ARCANE_HOME` set to a temp dir over patching `create_container`; older tests here still patch it.
- Integration tests in `tests/integration/` — real SQLite (temp file), no network. `test_installed_mcp.py` builds and installs the wheel (`-m artifact`).
- Plugin tests in `tests/plugins/` and `tests/unit/test_embeddings.py` — the only places network is faked: GitHub, Linear and Ollama need live credentials or a running server, so their HTTP calls are patched.
- `tests/unit/` holds only pure functions with many edge cases (redaction patterns, scope and remote parsing, FTS escaping, rank fusion). Keep it that way.

When you do patch, use the full dotted path where the name is **used**, not where it is defined:
```python
# Correct
@patch("arcane.cli.memory.create_container")
# Wrong — doesn't intercept the import binding in the module
@patch("arcane.cli._utils.create_container")
```

### Redaction
`infra/redaction.py` runs before any persistence in `MemoryService.save()`. Built-in patterns are compiled at module load. Custom patterns come from `$ARCANE_HOME/.memoryignore`; one that is not a valid regex is dropped with a warning naming its line. `redact_values` redacts string values only, never mapping keys: every dict it sees has structural keys (model dumps, column names, `raw_data`), and rewriting one drops that field.

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
3. Add tests in `tests/plugins/test_my_plugin.py`, faking only the network calls; cover its MCP or CLI surface in `tests/e2e/`.
4. Wire a CLI command in `src/arcane/cli/ingest.py` (or appropriate group).

## Adding a New MCP Tool

1. Create or extend a file in `mcp_server/tools/`.
2. Define a handler function `(args: dict) -> str`.
3. Register it in `mcp_server/server.py`: add a `Tool` (name, description, JSON schema) to `list_tools()` and a `(handler, first_arg)` entry to the `handlers` dict. Add it to `CORE_TOOLS` only if it belongs in the default profile.
4. Add it to the tool sets in `tests/e2e/test_mcp_discovery.py` and cover its success and error paths with an e2e scenario. Put value limits (enums, minimum/maximum) in the JSON schema: the MCP SDK then rejects bad input with a clear message before the handler runs.

## Commit Style

Use conventional commits:
- `feat:` new feature
- `fix:` bug fix
- `refactor:` code restructuring, no behaviour change
- `test:` test additions/changes
- `docs:` documentation only
- `chore:` tooling, deps, config

---

## Arcane — Automatic Engineering Memory

You have access to **Arcane** through MCP tools. Use it automatically as part of normal work — do not wait to be asked.

> **Tool name conventions** differ by agent:
> - Claude Code: `mcp__arcane__memory_context`, `mcp__arcane__memory_save`, etc.
> - Forge / Codex: `mcp_arcane_tool_memory_context`, `mcp_arcane_tool_memory_save`, etc.
> The capability names below (`memory_context`, `memory_save`, …) refer to the same tools regardless of prefix.

### Core Rules

- Retrieve context before doing meaningful work.
- Search before saving to avoid duplicates.
- Save before finishing any task that involved a decision, bug fix, non-obvious learning, or milestone.
- Use journeys for multi-step investigations rather than isolated memories only.
- Never save secrets, tokens, or credentials.
- One precise memory is better than a long dump.

### At the start of every session
1. Call `memory_context` for the current project to load recent decisions and context.
2. If the request references prior work or "last time", call `memory_search` with task-specific terms.
3. If the task sounds like an ongoing investigation or spike, call `journey_list` for active journeys.

### Before researching anything
Call `memory_search` first — the answer may already be stored.

### When to save memories (automatically, without being asked)
- **Decision**: architecture choice, implementation tradeoff, tooling choice, agreed direction
- **Bug**: root cause discovered and fix implemented
- **Pattern**: reusable approach, best practice, or non-obvious gotcha
- **Learning**: non-obvious technical insight that will help future sessions
- **Milestone**: significant feature, migration, or project progress point shipped

Save triggers: after a meaningful commit, after resolving a debugging session, after concluding a design discussion.

### Memory save fields — always include
- `project`: current project name
- `title`: short and specific, max 60 chars
- `what`: 1–2 sentence summary
- `why`: reasoning or motivation
- `impact`: what changed or why it matters
- `category`: `decision` | `bug` | `pattern` | `learning` | `context` | `poc` | `milestone`
- `tags`: 2–5 relevant tags
- `details`: for decisions and bugs, include context, options considered, decision, tradeoffs, follow-up

### Journeys — for multi-step investigations
Start `journey_start` for: difficult debugging, architectural evaluations, spikes, migrations, CI investigations.

While active: save related memories with `journey_id` set; call `journey_update` at major turning points.

When done: call `journey_complete` with a concise outcome summary.

### Content generation
- Use `draft_adr` when the user asks for an ADR and a relevant decision memory exists.
- Use `draft_blog` when the user asks for a blog post or retrospective and a journey exists.
