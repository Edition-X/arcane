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
│   ~/.arcane/arcane.db  (SQLite + FTS5 + sqlite-vec)     │
│   ~/.arcane/config.yaml                                  │
│   ~/.arcane/vault/<project>/YYYY-MM-DD-session.md       │
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

A derived observation produced by an intelligence plugin — for example, a detected CI flake pattern or an engineering velocity summary. Insights have an `acknowledged` flag so they surface once and then stay out of the way.

---

## Search: hybrid FTS5 + vector

Every search request goes through the hybrid search pipeline in `src/arcane/infra/search.py`:

1. **FTS5 full-text search** — fast keyword matching against title, what, why, impact, and tags using SQLite FTS5.
2. **Vector similarity search** — cosine similarity over embeddings stored with sqlite-vec, using whichever embedding provider is configured (Ollama or OpenAI).
3. **Result fusion** — scores from both passes are merged and ranked. Recent memories receive a small recency boost when `context.topup_recent` is enabled.

When no embedding provider is available (provider set to `none` or API key missing), Arcane falls back to FTS5-only search.

---

## Storage

All persistent data lives in a single SQLite file at `~/.arcane/arcane.db` (or `$ARCANE_HOME/arcane.db`). This makes it trivial to back up, sync with a tool like `syncthing`, or inspect directly with any SQLite client.

A markdown mirror of saved memories is written to `~/.arcane/vault/<project>/YYYY-MM-DD-session.md` — a human-readable record you can commit to a private git repo or read in any text editor.

---

## Plugin system

Arcane uses Python entry points for extensibility. Three plugin types are supported:

| Entry point group | Interface | Purpose |
|---|---|---|
| `arcane.plugins.ingestion` | `IngestionPlugin` | Import data from external systems |
| `arcane.plugins.intelligence` | `IntelligencePlugin` | Derive insights from stored data |
| `arcane.plugins.content` | `ContentPlugin` | Generate structured documents |

Install any package that declares the right entry point and Arcane will discover it automatically at startup.

---

## PII and secret redaction

Before any content is persisted, it passes through `src/arcane/infra/redaction.py`, which scrubs common secret patterns (API keys, tokens, connection strings) and PII (email addresses, phone numbers). Redacted spans are replaced with placeholder tokens so the structure of the text is preserved without leaking sensitive data.
