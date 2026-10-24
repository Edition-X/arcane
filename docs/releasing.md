# Releasing

Maintainers only. Releases are cut by hand; merging to `main` does not publish
anything.

## The shape of it

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | pull request | lint, tests on three Pythons, the whole suite on macOS and Windows, lowest-bound resolution, the installed wheel, the container image, docs |
| `main.yml` | push to `main` | builds the distribution and installs it on Linux, macOS and Windows. Publishes nothing. Proves the commit is releasable. |
| `release.yml` | manual | the release |
| `verify.yml` | called | installs a build and drives it over MCP stdio |
| `maintenance.yml` | weekly | Scorecard, full-history secret scan, lock drift, and a canary that reinstalls the current release |
| `codeql.yml` | pull request, weekly | static analysis |
| `pages.yml` | docs change, release | publishes `docs/` with a generated changelog |

## Cutting a release

1. Check that `main.yml` is green on the commit you intend to release.
   `release.yml` refuses to run otherwise — stable can only ever be something
   that has already been built and installed on all three platforms.
2. Run the **Release** workflow from the Actions tab on `main`.
   - **level** — `patch`, `minor` or `major`. The version is computed from the
     conventional commits since the last release.
   - **version** — set this only to override the computed version.
   - **dry-run** — builds, attests and verifies, then stops. Use it when you
     have changed the release workflow itself.
3. Watch it. The order is deliberate:

   ```
   plan ─ resolve the version, refuse to go backwards, generate notes
     └ build ─ tag locally, build, SBOM, attest provenance
         └ verify ─ install the wheel on 3 OSes × 2 Pythons, uv and pip, drive MCP
             └ github-release ─ create the tag and the release with assets
                 ├ pypi ─ trusted publishing, no token
                 └ image ─ multi-arch to GHCR, provenance attested
                     └ verify-published ─ reinstall from PyPI and the registry
                         └ quarantine ─ only if the above fails
   ```

   Nothing irreversible happens until the wheel has already been installed and
   driven on every supported platform.

## Versioning

The version lives in git tags; `hatch-vcs` derives the package version from
them. There is no version string in `pyproject.toml` to update.

Pre-1.0, a breaking change moves the minor version. `feat!:` takes 0.2.x to
0.3.0 — it does not declare 1.0. Promoting to 1.0 is a deliberate act: pass an
explicit `version` to the workflow.

Before 1.0 is worth doing, Arcane needs a versioned store schema with a tested
upgrade path, and an MCP tool surface that has held still for a few releases.
Until then the number says what it means.

The `v0.2.0-beta.N` tags are the abandoned continuous-beta series. `cliff.toml`
excludes them from `tag_pattern`, so they count neither for the changelog nor
for the version bump.

## If a release goes wrong

**Before publishing** — the run fails and leaves nothing behind. The tag is
created locally in the build job and only pushed once verification passes, so
a failed release has no tag, no release and no upload. Fix it and run again.

**After publishing** — `verify-published` failed. The `quarantine` job has
already marked the GitHub release as a prerelease and dropped it from latest,
and opened an issue. Two things still need a person:

- yank `arcane-mcp==<version>` on PyPI (a release can be yanked, never deleted)
- point `ghcr.io/edition-x/arcane:latest` back at the previous good digest

Then fix forward. Do not try to reuse the version number: PyPI will not accept
a second upload under it.

## First release checklist

One-time setup, needed before `release.yml` can publish:

- [ ] Reserve `arcane-mcp` on PyPI
- [ ] Add a PyPI [trusted publisher](https://docs.pypi.org/trusted-publishers/):
      owner `Edition-X`, repository `arcane`, workflow `release.yml`,
      environment `pypi`
- [ ] Create the `pypi` environment in repository settings, limited to the
      `main` branch
- [ ] Enable GitHub Pages, source "GitHub Actions"
- [ ] Enable Dependabot alerts and security updates
- [ ] Switch the required status check on `main` to `ci`
