"""Shared utilities for CLI command modules.

Centralises the ``create_container`` import so tests have a single patch
target: ``arcane.cli._utils.create_container``.
"""

from arcane.services.container import ServiceContainer, create_container

__all__ = ["ServiceContainer", "create_container"]
