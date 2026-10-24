# How It Works

## Layer diagram

```
┌─────────────────────────────────────────────────────────┐
│              Interfaces                                  │
│   CLI (Click)              MCP Server (stdio/JSON-RPC)  │
│   src/arcane/cli/          src/arcane/mcp_server/        │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Services                                    │
│   MemoryService   JourneyService   (+ plugin runners)   │
│   src/arcane/services/                                   │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Repositories + Infrastructure               │
│   MemoryRepo  JourneyRepo  ArtifactRepo  InsightRepo    │
│   HybridSearch  EmbeddingProvider  Redaction            │
│   src/arcane/infra/                                      │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Storage                                     │
│   ~/.arcane/index.db  (SQLite + FTS5 + sqlite-vec)        │
│   ~/.arcane/config.yaml                                  │
│   ~/.arcane/vault/@<org>/<project>/date-session.md        │
└─────────────────────────────────────────────────────────┘
```

---

## Entity types

### Memory

The core unit of knowledge. A memory captures a decision, bug, pattern, learning, context note, poc finding, or milestone. Each memory has:

- A short `title` and 1–2 sentence `what`
- Optional `why`, `impact`, and extended `details`
- A `category`, `tags`, and `project`
- Optional `ttl_days` (expiry) and `confidence` score
- A vector embedding for semantic retrieval

### Journey

A narrative arc tracking a multi-step investigation from problem through to outcome. Journeys can have many linked memories and artifacts. States: `active` → `completed` or `abandoned`.

### Artifact

An external reference ingested from a third-party system — a git commit, a GitHub Actions run, or a Linear ticket. Artifacts are searchable and linkable to memories and journeys.

### Relationship

A typed directed edge between any two entities. Relationship types include `caused_by`, `implements`, `supersedes`, `related_to`, and others defined in `arcane.domain.enums.RelationType`. Together, relationships form a knowledge graph you can traverse with the `trace` tool.

### Insight

A derived observation produced by an intelligence plugin — for example, an engineering velocity summary. Insights have an `acknowledged` flag so they surface once and then stay out of the way.

---

## Search: hybrid FTS5 + vector

Every search request goes through the hybrid search pipeline in `src/arcane/infra/search.py`:

1. **FTS5 full-text search** — fast keyword matching against title, what, why, impact, and tags using SQLite FTS5.
2. **Vector search** — sqlite-vec ranks embeddings by L2 (Euclidean) distance using the configured provider (Ollama or OpenAI). Distance becomes a positive score with `1 / (1 + distance)`; closer vectors score higher.
3. **Result fusion** — each backend's scores are divided by its best score, then combined with weights of 0.3 for FTS and 0.7 for vectors. Scope specificity adds a small bonus. Context can supplement results with recent memories when `context.topup_recent` is enabled.

When no embedding provider is available (provider set to `none` or API key missing), Arcane falls back to FTS5-only search.

---

## Storage

All persistent data lives in a single SQLite file at `~/.arcane/index.db` (or `$ARCANE_HOME/index.db`). This makes it trivial to back up, sync with a tool like `syncthing`, or inspect directly with any SQLite client.

A Markdown mirror of project memories is written to `~/.arcane/vault/@<org>/<project>/YYYY-MM-DD-session.md`. Org memories omit the project directory; global memories live directly under `vault/`. These are human-readable records you can keep in a private git repo or read in any text editor.

Stored file paths are relative to the data home (`vault/...`), and API responses give the current absolute path. Moving or restoring the home keeps new paths usable. Legacy absolute paths resolve only inside the current vault, so a restored copy cannot edit the original vault through an old path.

---

## Plugin system

Arcane uses Python entry points for extensibility. Three plugin types are supported:

| Entry point group | Interface | Purpose |
|---|---|---|
| `arcane.plugins.ingestion` | `IngestionPlugin` | Import data from external systems |
| `arcane.plugins.intelligence` | `IntelligencePlugin` | Derive insights from stored data |
| `arcane.plugins.content` | `ContentPlugin` | Generate structured documents |

The registry drives both built-in and third-party execution. Install plugins into Arcane's Python environment; their entry-point names appear under `arcane ingest`, `arcane analyze`, or `arcane draft`. Existing built-in commands and tools remain available.

Use a group's `--list` or `--help` to discover plugins. An added plugin command's `--help` shows its constructor signature. Supply constructor settings with `--options '{"key":"value"}'`, and content input with `--context '{"topic":"release"}'`.

The full MCP profile's `plugins` tool lists all kinds when called without arguments. Supply `kind` and `plugin_name` to execute a plugin, with optional `options` and content `context` objects. The `analyze` tool also accepts installed intelligence entry-point names.

Factories may declare `memory_repo`, `artifact_repo`, `journey_repo`, `retrieval_repo`, `aliases`, and `org` parameters to receive Arcane's repositories, project aliases, and resolved org. Only explicitly declared parameters receive these values; `options` cannot override them.

---

## Secret redaction

Before content is persisted or embedded, `src/arcane/infra/redaction.py` removes known secret formats (API keys, tokens, private keys, JWTs, and credential assignments). User-defined regexes in `$ARCANE_HOME/.memoryignore` are also applied by Arcane services. Search queries and batch embeddings use the same redaction rules before they reach a provider. Explicit `<redacted>` spans support nesting; an unclosed opener hides the remaining input, and an unmatched closer hides the preceding input. This is not generic PII redaction: email addresses, phone numbers, and other personal data are retained unless a user-defined pattern matches them. Redacted spans are replaced with `[REDACTED]`.
