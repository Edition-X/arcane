"""MCP resource definitions for Arcane."""

from __future__ import annotations

RESOURCE_TEMPLATE_URI = "arcane://context/{project}"


def _parse_project_from_uri(uri: str) -> str:
    """Extract project name from an arcane://context/{project} URI."""
    prefix = "arcane://context/"
    if uri.startswith(prefix):
        return uri[len(prefix) :]
    # fallback: take last path component
    return uri.rstrip("/").rsplit("/", 1)[-1]
