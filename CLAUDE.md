# Arcane — Project Instructions for Claude Code

## What This Project Is

Arcane is a personal engineering memory MCP server. It exposes tools for saving/searching memories, tracking decision journeys, ingesting artifacts from CI/Linear/Git, and generating blog posts or ADRs. The canonical data store is SQLite with FTS5 + sqlite-vec for hybrid search.

## MCP Server

The MCP server is the primary interface for AI agents. Run it with:
```bash
arcane mcp
```
It communicates via stdio (JSON-RPC). For Claude Desktop / Claude Code integration, add it to your MCP config:
```json
{
  "mcpServers": {
    "arcane": {
      "command": "arcane",
      "args": ["mcp"]
    }
  }
}
```

## Development Priorities

- **No regressions**: always run `pytest` before committing
- **Type safety**: new public functions must have type annotations; run `mypy src/arcane` after changes
- **DRY**: check existing services and repos before adding new logic
- **Test at boundaries**: mock DB and network at the service/repo boundary, not deep inside

## Arcane Memory Discipline (for Claude Code)

Arcane is the persistent memory system for this project. Use it automatically — do not wait to be asked.

### At the start of every session
1. Call `memory_context` for the current project to load recent decisions, bugs, and context.
2. If the request references prior work, past decisions, or "last time", call `memory_search` with task-specific terms.
3. If the task sounds like an ongoing investigation or spike, call `journey_list` to find active journeys.

### Before researching anything
- Call `memory_search` first — the answer may already be stored.

### When to save memories (after every `git commit`)
- **Decision made** → `memory_save` with `category: "decision"`
- **Bug fixed** → `memory_save` with `category: "bug"`, including root cause and how to recognise it
- **Pattern discovered** → `memory_save` with `category: "pattern"` or `"learning"`
- **Milestone shipped** → `memory_save` with `category: "milestone"`

One focused memory per commit is better than a large dump at session end.

### Journeys — for multi-step investigations
- Start with `journey_start` when work spans multiple steps (debugging, architectural evaluation, spike).
- Link memories via `journey_id` as the work progresses.
- Complete with `journey_complete` and an outcome summary when done.

### Memory save fields — always include
`title` (≤60 chars), `what`, `why`, `impact`, `category`, `tags`, `project`, `details` (for decisions/bugs).

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `ARCANE_HOME` | Override data directory | `~/.arcane` |
| `GITHUB_TOKEN` | GitHub API auth for GHA ingest | — |
| `LINEAR_API_KEY` | Linear API key | — |
| `OPENAI_API_KEY` | OpenAI embeddings | — |
| `ARCANE_LOG_LEVEL` | Log verbosity (`DEBUG`/`INFO`/`WARNING`) | `INFO` |

## Project Structure Quick-Ref

| Path | Responsibility |
|---|---|
| `src/arcane/cli/` | Click CLI, one file per command group |
| `src/arcane/domain/models.py` | Pydantic domain models |
| `src/arcane/infra/db/` | SQLite schema + repository classes |
| `src/arcane/infra/config.py` | Config loading (YAML → Pydantic) |
| `src/arcane/infra/search.py` | Hybrid FTS + vector search |
| `src/arcane/infra/redaction.py` | PII/secret scrubbing before persistence |
| `src/arcane/mcp_server/server.py` | MCP tool registration + dispatcher |
| `src/arcane/mcp_server/tools/` | Individual tool handler modules |
| `src/arcane/plugins/` | Plugin protocols + built-in implementations |
| `src/arcane/services/` | Business logic layer |

## Running Tests

```bash
pytest                          # all tests
pytest tests/unit/              # fast unit tests only
pytest tests/integration/       # DB integration tests
pytest -x -q                    # fail fast, quiet output
```

## Common Tasks

**Add a new memory category**: update `Category` enum in `domain/models.py` — the validator auto-picks it up.

**Add a new CLI command**: add a function in the appropriate `cli/*.py` module, register it with Click, add the command to the group.

**Change embedding model**: edit `~/.arcane/config.yaml` (or project config) and run `arcane reindex` to rebuild vectors.

**Debug MCP tools**: set `ARCANE_LOG_LEVEL=DEBUG` and check stderr output.
