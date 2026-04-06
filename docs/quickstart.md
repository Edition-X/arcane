# Quickstart

## Connect to Claude Code

Add Arcane to your Claude Code MCP config. You can do this globally (`~/.claude/config.json`) or per-project (`.claude/config.json` in a project directory):

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

Restart Claude Code — the Arcane tools will be available automatically.

---

## Connect to Claude Desktop

Add the same block to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the equivalent path on your platform:

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

Restart Claude Desktop to pick up the new server.

---

## Save your first memory

Once connected, ask Claude to save something — or trigger it yourself via the `memory_save` tool:

```
Save a memory:
  title: "Use pgbouncer for connection pooling"
  what: "We switched to pgbouncer to handle connection spikes from the worker fleet."
  why: "Direct connections from 50+ workers exhausted the Postgres connection limit."
  impact: "p99 connection latency dropped from 800ms to 40ms."
  category: decision
  project: my-project
  tags: ["postgres", "infra", "performance"]
```

---

## Search memories

Use `memory_search` to query across everything you've saved:

```
Search memories for: postgres connection pooling
```

Results are ranked by hybrid FTS + vector similarity, so natural language queries work well.

---

## Load project context

At the start of a session, `memory_context` loads the most relevant memories for the current project:

```
Get memory context for project: my-project
```

This is called automatically by Claude agents following the Arcane conventions.

---

## Start a journey

Journeys track multi-step investigations — useful when evaluating a technology, debugging a hard problem, or designing a system:

```
Start a journey:
  title: "Evaluate vector DB options for semantic search"
  project: my-project
```

Then add updates as you go with `journey_update`, and close it with `journey_complete` when you have an outcome.

---

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ARCANE_HOME` | Override data directory | `~/.arcane` |
| `OPENAI_API_KEY` | OpenAI API key for cloud embeddings | — |
| `ARCANE_LOG_LEVEL` | Log verbosity: `DEBUG`, `INFO`, `WARNING` | `INFO` |
| `GITHUB_TOKEN` | GitHub API auth for GHA ingestion | — |
| `LINEAR_API_KEY` | Linear API key for ticket ingestion | — |

---

## Next steps

- [MCP Tools reference](mcp-tools.md) — full parameter documentation for every tool
- [Configuration](configuration.md) — switch embedding providers, tune context retrieval
