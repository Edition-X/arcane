# MCP Tools Reference

Arcane exposes 19 tools, 1 resource template, and 3 prompts to MCP-compatible agents.

---

## Memory tools

### `memory_save`

Save a memory for future sessions. Call this before ending any session where you made changes, fixed bugs, made decisions, or learned something.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | Short title, max 60 characters |
| `what` | string | yes | 1–2 sentences — the essence of the memory |
| `why` | string | no | Reasoning behind the decision or action |
| `impact` | string | no | What changed or what it affects |
| `tags` | array of strings | no | 2–5 relevant tags |
| `category` | string | no | One of: `decision`, `bug`, `pattern`, `learning`, `context`, `poc`, `milestone` |
| `related_files` | array of strings | no | File paths relevant to this memory |
| `details` | string | no | Full context — options considered, tradeoffs, follow-up |
| `project` | string | no | Project name (defaults to current directory name) |
| `journey_id` | string | no | Link this memory to an active journey |
| `ttl_days` | integer | no | Days until this memory expires from search results. Omit for permanent memories. |
| `confidence` | number | no | Confidence in accuracy 0.0–1.0. Omit if not applicable. |

**Categories:**

| Category | Use for |
|---|---|
| `decision` | Architectural or design decisions — include tradeoffs in `details` |
| `bug` | Bugs you fixed — root cause, fix, and how to recognise it |
| `pattern` | Reusable patterns or best practices |
| `learning` | Things you discovered or figured out |
| `context` | Background knowledge about a project or system |
| `poc` | Proof-of-concept or spike findings |
| `milestone` | Significant work shipped |

**In `details`, prefer this structure:** Context, Options considered, Decision, Tradeoffs, Follow-up.

---

### `memory_search`

Search memories using keyword and vector search. Call at session start and whenever the user's request relates to a topic with prior context.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Search query (natural language or keywords) |
| `limit` | integer | no | Number of results to return (default: 5) |
| `project` | string | no | Restrict search to a specific project |

---

### `memory_context`

Get memory context for the current project. Call at session start to load prior decisions, bugs, and context.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project` | string | no | Project name (defaults to current directory name) |
| `limit` | integer | no | Number of memories to return (default: 10) |
| `detail` | string | no | Level of detail per memory — see below |

**`detail` levels:**

| Level | Fields returned | Approx tokens (10 memories) |
|---|---|---|
| `minimal` | `id`, `title`, `category` | ~500 |
| `standard` | `id`, `title`, `category`, `tags`, `date`, `what` | ~1 500 |
| `full` | All fields including `why` and `impact` | ~3 000 |

Default is `standard`. Use `minimal` when token budget is tight; use `full` when you need the complete picture for a small result set.

---

### `memory_details`

Get full details for a single memory, including the extended `details` field.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `memory_id` | string | yes | Memory ID or unambiguous prefix |

---

### `memory_delete`

Delete a memory permanently.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `memory_id` | string | yes | Memory ID or unambiguous prefix |

---

## Journey tools

Journeys are decision narrative arcs — use them for multi-step investigations, technology evaluations, or hard debugging sessions.

### `journey_start`

Begin tracking a decision journey.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | Short description of the investigation |
| `project` | string | no | Project name |
| `linear_issue_id` | string | no | Link to a Linear issue |

---

### `journey_update`

Add a progress update to an active journey.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `journey_id` | string | yes | Journey ID or prefix |
| `summary` | string | no | What you found or decided at this step |

---

### `journey_complete`

Mark a journey as completed with a final outcome summary.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `journey_id` | string | yes | Journey ID or prefix |
| `summary` | string | no | Final outcome and what was decided |

---

### `journey_list`

List journeys, optionally filtered by project or status.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project` | string | no | Filter by project |
| `status` | string | no | One of: `active`, `completed`, `abandoned` |
| `limit` | integer | no | Number to return (default: 10) |

---

## Relationship tools

### `link`

Create a typed relationship between two entities (memory, journey, or artifact).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `source_type` | string | yes | `memory`, `journey`, or `artifact` |
| `source_id` | string | yes | Source entity ID |
| `target_type` | string | yes | `memory`, `journey`, or `artifact` |
| `target_id` | string | yes | Target entity ID |
| `relation` | string | yes | Relationship type (e.g. `caused_by`, `implements`, `supersedes`) |

---

### `trace`

Walk the relationship graph outward from an entity to find connected knowledge.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_type` | string | yes | `memory`, `journey`, or `artifact` |
| `entity_id` | string | yes | Starting entity ID |
| `max_depth` | integer | no | Maximum hops to follow (default: 5) |

---

## Intelligence tools

### `insights`

Get recent unacknowledged insights for a project (e.g. detected CI flakes, velocity summaries).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project` | string | no | Filter by project |
| `limit` | integer | no | Number to return (default: 10) |

---

### `insights_ack`

Acknowledge an insight so it no longer appears in unacknowledged lists.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `insight_id` | string | yes | Insight ID to acknowledge |

---

## Ingestion tools

### `ingest_git`

Import commits from a local git repository as searchable artifacts.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project` | string | no | Project name to tag the artifacts |
| `repo_path` | string | no | Path to the git repository (defaults to current directory) |
| `max_count` | integer | no | Maximum number of commits to import (default: 100) |
| `journey_id` | string | no | Link ingested artifacts to a journey |

---

### `ingest_gha`

Import CI runs from GitHub Actions as artifacts.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `owner` | string | yes | GitHub repository owner |
| `repo` | string | yes | GitHub repository name |
| `project` | string | no | Project name to tag the artifacts |
| `journey_id` | string | no | Link ingested artifacts to a journey |

Requires `GITHUB_TOKEN` to be set.

---

### `ingest_linear`

Import tickets from Linear as artifacts.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `team_id` | string | yes | Linear team ID |
| `project` | string | no | Project name to tag the artifacts |
| `journey_id` | string | no | Link ingested artifacts to a journey |

Requires `LINEAR_API_KEY` to be set.

---

## Analysis tools

### `analyze`

Run an intelligence analysis plugin against stored data.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `plugin_name` | string | yes | `ci_flakes` or `velocity` |
| `project` | string | no | Project to analyse |

- **`ci_flakes`** — detects flaky CI tests by examining GHA artifact history
- **`velocity`** — summarises engineering output rate from commits and closed tickets

Results are stored as Insights and returned in the response.

---

## Content tools

### `draft_blog`

Generate a structured blog post brief from a completed journey.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `journey_id` | string | no | Journey to base the brief on |
| `project` | string | no | Fallback to recent project memories if no journey specified |

Returns a blog brief with suggested title, hook, sections, and key takeaways.

---

### `draft_adr`

Generate an Architecture Decision Record from a `decision` category memory.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `memory_id` | string | yes | ID of a decision memory |

Returns a structured ADR with context, decision, consequences, and alternatives considered.

---

## MCP Resources

### `arcane://context/{project}`

A resource template that returns the standard memory context for a project as JSON. MCP hosts can pre-fetch this at session start without invoking the `memory_context` tool explicitly.

```
arcane://context/my-project
```

Returns the same payload as `memory_context` with `detail=standard`.

---

## MCP Prompts

Prompts are pre-built instruction templates that Claude can invoke by name.

### `/recall`

Search Arcane memory for past decisions, bugs, or patterns related to a topic.

| Argument | Required | Description |
|---|---|---|
| `query` | yes | Topic or question to search for |
| `project` | no | Project name to search within |

---

### `/catchup`

Summarise recent engineering activity and decisions for a project.

| Argument | Required | Description |
|---|---|---|
| `project` | yes | Project name |
| `limit` | no | Number of recent memories to include (default: 10) |

---

### `/journey`

Show the full decision narrative for a journey — problem, exploration, and outcome.

| Argument | Required | Description |
|---|---|---|
| `journey_id` | yes | Journey ID or prefix |
