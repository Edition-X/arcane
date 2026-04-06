# Arcane

> **Beta software** — Arcane is in active development. APIs and storage formats may change between releases. Pin your version and back up `~/.arcane` before upgrading.

**Unified engineering intelligence** — persistent memory, decision journeys, and knowledge capture for AI-assisted development workflows.

Arcane runs as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server, giving Claude Code, Claude Desktop, and other MCP-compatible agents a persistent, searchable knowledge store that survives context window resets and spans every project you work on.

---

## What It Does

- **Memories** — save and search decisions, bugs, patterns, and learnings with hybrid FTS + vector search
- **Journeys** — track multi-step investigations from problem → exploration → decision → outcome
- **Artifacts** — ingest CI runs, git commits, and Linear tickets as searchable references
- **Relationships** — link any entities (memory → memory, journey → artifact, etc.) into a knowledge graph
- **Content generation** — draft blog posts and Architecture Decision Records from your stored knowledge
- **Intelligence** — detect CI flake patterns and summarise engineering velocity

---

## Quickstart

### Install

```bash
# With uv (recommended)
uv tool install arcane

# Or with pip
pip install arcane
```

### Initialise

```bash
arcane init
```

This creates `~/.arcane/` with a SQLite database and default config.

### Connect to Claude Code

Add to your Claude Code MCP config (`~/.claude/config.json` or project `.claude/config.json`):

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

Restart Claude Code — Arcane tools will be available automatically.

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

---

## MCP Tools

Once connected, Claude has access to these tools:

| Tool | Purpose |
|---|---|
| `memory_save` | Save a decision, bug, pattern, or learning |
| `memory_search` | Semantic + keyword search across all memories |
| `memory_context` | Load relevant memories for the current project |
| `memory_details` | Fetch full details for a specific memory |
| `memory_delete` | Remove a memory by ID |
| `journey_start` | Begin tracking a multi-step investigation |
| `journey_update` | Add a progress update to a journey |
| `journey_complete` | Mark a journey done with an outcome summary |
| `journey_list` | List active or recent journeys |
| `ingest_git` | Import commits from a git repository |
| `ingest_gha` | Import CI runs from GitHub Actions |
| `ingest_linear` | Import tickets from Linear |
| `analyze` | Run intelligence plugins (flakes, velocity) |
| `insights` / `insights_ack` | View and acknowledge derived insights |
| `link` | Create a relationship between two entities |
| `trace` | Walk the relationship graph from an entity |
| `draft_blog` | Generate a structured blog post brief |
| `draft_adr` | Generate an ADR from a decision memory |

---

## CLI Reference

```bash
# Memory
arcane save                     # Interactive save
arcane search "query"           # Hybrid search
arcane context                  # Print context for agent injection
arcane details <id-prefix>      # Full memory details
arcane delete <id-prefix>       # Delete a memory
arcane reindex                  # Rebuild vector index
arcane stats                    # DB statistics
arcane sessions                 # List recent sessions

# Journeys
arcane journey start            # Start a journey
arcane journey update <id>      # Add an update
arcane journey complete <id>    # Mark complete
arcane journey list             # List journeys
arcane journey show <id>        # Full journey with linked entities

# Ingestion
arcane ingest git               # Ingest local git commits
arcane ingest gha               # Ingest GitHub Actions runs
arcane ingest linear            # Ingest Linear tickets

# Intelligence
arcane analyze flakes           # Detect CI flakes
arcane analyze velocity         # Engineering velocity summary

# Content
arcane draft blog               # Blog brief from memories
arcane draft adr <memory-id>    # ADR from a decision memory

# Relationships
arcane link <type-id> <type-id> <rel-type>   # Create link
arcane trace <type> <id>                      # Walk graph

# Config
arcane config                   # Show current config
arcane config set-home <path>   # Set custom data directory
arcane config clear-home        # Remove custom home setting

# Server
arcane mcp                      # Start MCP server (stdio)
arcane -v mcp                   # With debug logging
```

---

## Configuration

Config is loaded from `~/.arcane/config.yaml` (or `$ARCANE_HOME/config.yaml`):

```yaml
embedding:
  provider: ollama           # "ollama" or "openai"
  model: nomic-embed-text    # Embedding model name
  base_url: http://localhost:11434  # Ollama base URL (ignored for openai)
  api_key: null              # OpenAI API key (or set OPENAI_API_KEY env var)

context:
  semantic: auto             # "auto" | "always" | "never"
  topup_recent: true         # Supplement semantic results with recent memories
```

### Environment Variables

| Variable | Purpose |
|---|---|
| `ARCANE_HOME` | Override data directory (default: `~/.arcane`) |
| `GITHUB_TOKEN` | GitHub API auth for GHA ingestion |
| `LINEAR_API_KEY` | Linear API key for ticket ingestion |
| `OPENAI_API_KEY` | OpenAI API key (alternative to config file) |
| `ARCANE_LOG_LEVEL` | Log verbosity: `DEBUG`, `INFO`, `WARNING` |

---

## Semantic Search

Arcane supports two embedding backends:

### Ollama (default, local, free)

```bash
# Install Ollama: https://ollama.ai
ollama pull nomic-embed-text

# Config (default — no changes needed)
embedding:
  provider: ollama
  model: nomic-embed-text
```

### OpenAI

```bash
# Set API key
export OPENAI_API_KEY=sk-...
```

```yaml
# config.yaml
embedding:
  provider: openai
  model: text-embedding-3-small
```

After switching models, rebuild the vector index:

```bash
arcane reindex
```

---

## Memory Categories

| Category | Use for |
|---|---|
| `decision` | Architectural or design decisions (include tradeoffs in `details`) |
| `bug` | Bugs you fixed — root cause, fix, and how to recognise it |
| `pattern` | Reusable patterns or best practices |
| `learning` | Things you discovered or figured out |
| `context` | Background knowledge about a project or system |
| `poc` | Proof-of-concept or spike findings |
| `milestone` | Significant work shipped |

---

## Plugin System

Arcane uses Python entry points for extensibility. Install any package that declares the right entry point and Arcane will discover it automatically.

```toml
# In your plugin package's pyproject.toml
[project.entry-points."arcane.plugins.ingestion"]
jira = "my_package:JiraIngestionPlugin"

[project.entry-points."arcane.plugins.intelligence"]
code_churn = "my_package:CodeChurnAnalyser"

[project.entry-points."arcane.plugins.content"]
changelog = "my_package:ChangelogGenerator"
```

Plugins must implement the protocols defined in `arcane.plugins.protocols`.

---

## Data Layout

```
~/.arcane/
├── arcane.db          # SQLite database (memories, journeys, artifacts, relationships)
└── vault/
    └── <project>/
        └── YYYY-MM-DD-session.md   # Markdown mirror of saved memories
```

All data lives in a single SQLite file — easy to back up, sync, or inspect with any SQLite tool.

---

## Development

```bash
git clone https://github.com/dkelly/arcane
cd arcane
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pre-commit install

# Run tests
pytest

# Lint + format
ruff check --fix src/ tests/
ruff format src/ tests/

# Type check
mypy src/arcane
```

### Project Structure

```
src/arcane/
├── cli/            # Click CLI — one module per command group
├── domain/         # Pydantic domain models
├── infra/          # DB repos, config, search, embeddings, redaction
├── mcp_server/     # MCP stdio server + tool handlers
├── plugins/        # Plugin protocols + built-in implementations
└── services/       # Business logic layer
```

See [AGENTS.md](./AGENTS.md) for detailed contributor and agent guidance.

---

## License

[MIT](./LICENSE)
