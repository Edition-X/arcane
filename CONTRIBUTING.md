# Contributing

Arcane is a personal project that happens to be public. Issues and pull
requests are welcome; expect replies to be unhurried.

## Getting set up

```bash
git clone https://github.com/Edition-X/arcane.git
cd arcane
uv sync --extra dev
uv run pre-commit install
```

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/). Nothing
else: the test suite never reaches the network and never starts a real Ollama.

## Before you open a pull request

```bash
uv run ruff format src tests scripts
uv run ruff check src tests scripts
uv run mypy src/arcane
uv run pytest -q
```

`ruff format` goes before `ruff check` so formatting fixes do not fight the
linter. `pytest -q` includes the `artifact` test, which builds a wheel,
installs it into a throwaway virtualenv and drives the real MCP server over
stdio — slower than the rest, and the one most likely to catch a packaging
mistake.

## How this project tests

There are no mocked unit tests. Tests drive the real entry point — the `arcane`
CLI, or the `arcane mcp` server over stdio — against a real temporary SQLite
store. `tests/e2e/conftest.py` gives you a connected MCP session, a throwaway
`ARCANE_HOME` and a git repository with a fake remote, which is usually all a
new test needs. Only GitHub, Linear and Ollama are faked, because they are
someone else's network.

If you add, rename or change an MCP tool, update `docs/mcp-tools.md` in the
same change. A test compares the reference against what the server actually
exposes and fails on drift.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/). The release
notes and the version bump are generated from them, so the prefix decides what
your change is called and how it moves the version:

| prefix | effect |
|---|---|
| `fix:` | patch |
| `feat:` | minor |
| `feat!:` / `BREAKING CHANGE:` | minor while the project is pre-1.0 |
| `docs:`, `perf:`, `refactor:`, `revert:` | appear in the notes |
| `chore:`, `test:`, `style:`, `chore(ci):` | omitted from the notes |

## What CI will do to your pull request

- **Lint** — ruff, mypy, gitleaks, plus actionlint and zizmor over the
  workflows themselves.
- **Test** — Python 3.11, 3.12 and 3.13 on Linux; the whole suite on macOS and
  Windows; and one run resolved to the lowest versions your declared
  dependency bounds allow.
- **Installed artifact** — builds the wheel and drives it over MCP stdio.
- **Docker** — builds the image and serves MCP from it.
- **Dependency review** — fails on a new dependency with a known high-severity
  advisory or a non-permissive licence.

A single `ci` check aggregates all of it; that is the one that has to be green.
Jobs your change cannot affect are skipped, and anything touching `.github/`
runs the lot.

## Releasing

Maintainers only, and never automatic. See [`docs/releasing.md`](docs/releasing.md).
