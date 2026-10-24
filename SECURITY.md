# Security Policy

## Reporting a vulnerability

Report privately through
[GitHub Security Advisories](https://github.com/Edition-X/arcane/security/advisories/new).
Please do not open a public issue for anything exploitable.

Expect an acknowledgement within a week. If a fix is warranted it ships in the
next release and the advisory is published alongside it.

## What Arcane handles

Arcane stores engineering notes in a local SQLite database under `~/.arcane`.
It is a single-user local process, not a service. The things most worth
reporting are therefore:

- content written to the store escaping redaction (`src/arcane/infra/redaction.py`)
  and reaching disk, logs or generated output in the clear
- a path in the MCP tool surface that reads or writes outside `ARCANE_HOME`
- anything in the ingestion plugins (GitHub, Linear, git) that executes or
  interpolates fetched content

Arcane never writes credentials to the store. If you find one there, that is a
bug worth reporting.

## Verifying what you installed

Every wheel, source distribution and container image is built by the Release
workflow and published with build provenance. You can check that an artifact
came from this repository and from that workflow, rather than from someone's
laptop:

```bash
# A wheel or sdist downloaded from the GitHub release
gh attestation verify --owner Edition-X arcane_mcp-0.2.0-py3-none-any.whl

# The container image
gh attestation verify --owner Edition-X oci://ghcr.io/edition-x/arcane:0.2.0
```

Distributions on PyPI additionally carry
[PEP 740](https://peps.python.org/pep-0740/) attestations, published through
trusted publishing. There is no API token for this project stored in GitHub —
the release workflow authenticates to PyPI with a short-lived OIDC identity,
so there is nothing to leak or rotate.

## Supported versions

The latest release is supported. Fixes are not backported.
