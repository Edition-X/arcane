# Configuration

## Config file location

Arcane reads its configuration from `~/.arcane/config.yaml` (or `$ARCANE_HOME/config.yaml`). The file is optional and `arcane init` does not create it: write it when you want to change a default. Every field is optional, and missing values fall back to the defaults shown below. `arcane config` prints the settings in effect.

```yaml
embedding:
  provider: ollama              # Embedding backend: "ollama", "openai", or "none"
  model: nomic-embed-text       # Model name (provider-specific)
  base_url: http://localhost:11434  # Ollama API base URL (ignored for openai)
  autostart: true               # Start a local Ollama when it is not running (ollama only)
  api_key: null                 # Required when provider is openai

context:
  semantic: auto                # When to use vector search: "auto", "always", or "never"
  topup_recent: true            # Add recent memories to supplement semantic results
```

---

## Embedding providers

### Ollama (default — local, free)

Runs entirely on your machine. Requires [Ollama](https://ollama.ai) to be installed and the chosen model pulled:

```bash
ollama pull nomic-embed-text
```

No API key needed. `base_url` defaults to `http://localhost:11434` — change it if you run Ollama on a different host or port.

**Autostart.** When `base_url` points at this machine and Ollama is not running, Arcane starts it:

- **When the MCP server starts**, a background thread probes Ollama and starts it if it is down, so it is usually up before the first save.
- **When an embed call finds nothing listening**, Arcane starts Ollama, waits up to 5 seconds, and retries once. A memory saved right after Ollama stopped still gets a vector.

On macOS with Ollama.app installed and the default port, Arcane runs `open -g -a Ollama`, which launches the app in the background without taking focus. Otherwise it runs a detached `ollama serve` bound to `base_url`'s host and port.

When Ollama is already up, the check costs one local HTTP request, under 1 ms. A start that fails is not retried for 60 seconds, so a broken install never slows every save. Arcane never starts a remote Ollama.

To turn autostart off, set `autostart: false` in the config or `ARCANE_OLLAMA_AUTOSTART=0` in the environment.

```yaml
embedding:
  provider: ollama
  model: nomic-embed-text
  base_url: http://localhost:11434
```

### OpenAI

Uses OpenAI's embedding API. Set `embedding.api_key` explicitly in the config file:

```yaml
embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: your-api-key
```

A missing or blank key reports a configuration error. Environment variables do not supply this key.

Recommended models: `text-embedding-3-small` (fast, cheap) or `text-embedding-3-large` (higher quality).

### None (FTS only)

Disable embeddings entirely — Arcane will use FTS5 keyword search only:

```yaml
embedding:
  provider: none
```

---

## Switching embedding models

After changing `provider` or `model`, rebuild the vector index so all existing memories are re-embedded with the new model:

```bash
arcane reindex
```

This is safe to interrupt and re-run — the index is rebuilt atomically.

---

## Context retrieval

The `context` section controls how `memory_context` and resource reads work.

| Field | Type | Default | Description |
|---|---|---|---|
| `semantic` | `"auto"` / `"always"` / `"never"` | `"auto"` | When to use vector similarity for context retrieval. `auto` enables it when embeddings are available. |
| `topup_recent` | boolean | `true` | Whether to supplement semantic results with the most recent memories, ensuring nothing brand new is missed. |

---

## Usage recording

The MCP server records every lookup (`memory_search`, `memory_context`, `memory_details`, `memory_update`, `journey_show`, `artifact_search`, `artifact_details` and the project context resource) with the agent, session, project and the IDs it returned. `arcane analyze usage` reports on it. The log stays in the local `index.db`.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Record lookups at all. |
| `log_queries` | boolean | `true` | Keep the search text, redacted like every other stored field. Off stores the lookup without it. |
| `retention_days` | integer | `180` | Lookups older than this are deleted when the MCP server starts. |

A search counts as a possible gap when it returned nothing, or when no memory contains its key words (all of them for up to three, all but one for longer searches), since vector search always returns its nearest neighbours.

---

## Orgs and projects

Every save and lookup resolves an org and a project from the working directory's git remote. These settings correct that when the remote is not enough.

```yaml
orgs:
  remotes:                   # git remote owner -> org slug
    Sunrise-Robotics: sunrise-robotics
  overrides:                 # canonical project name -> org, for forks and mirrors
    some-fork: personal
  default: personal          # org for repositories with no git remote

projects:
  aliases:                   # different names for the same work
    grafana-usage-report: grafana-usage-automation
```

Project names are canonicalised on every save and lookup: trimmed, lowercased, separators collapsed (`Edition X` becomes `edition-x`), `owner/repo` reduced to the repo name, then mapped through `projects.aliases`. To heal a project that already split in two, list the projects and merge one into the other:

```bash
arcane projects                                                              # projects with memory counts
arcane merge-projects grafana-usage-report grafana-usage-automation          # dry run
arcane merge-projects grafana-usage-report grafana-usage-automation --apply  # write the change
```

A merge moves one org's memories. When more than one org has a project with the source name, the command lists them and asks for `--org`.

---

## Near-duplicate warnings

`dedup.threshold` (default `0.92`) is the cosine similarity at which a new memory triggers a `near_duplicate` warning against an existing one. Raise it towards `1.0` to warn less. The warning never blocks a save.

---

## Environment variable reference

Environment variables take precedence over the config file.

| Variable | Purpose | Default |
|---|---|---|
| `ARCANE_HOME` | Override data directory | `~/.arcane` |
| `ARCANE_LOG_LEVEL` | Log verbosity: `DEBUG`, `INFO`, `WARNING` | `INFO` |
| `ARCANE_OLLAMA_AUTOSTART` | Set to `0` to stop Arcane starting a local Ollama (overrides `embedding.autostart`) | on |
| `GITHUB_TOKEN` | GitHub API auth for GHA ingestion | — |
| `LINEAR_API_KEY` | Linear API key for ticket ingestion | — |

---

## Home directory resolution order

Arcane resolves the data directory in this order (first match wins):

1. `ARCANE_HOME` environment variable
2. Persisted config (`arcane config set-home <path>` writes to `~/.config/arcane/config.yaml`)
3. Default: `~/.arcane`

To view the current resolution:

```bash
arcane config
```

To set a custom home permanently:

```bash
arcane config set-home /path/to/dir
```

To remove the override and fall back to the default:

```bash
arcane config clear-home
```
