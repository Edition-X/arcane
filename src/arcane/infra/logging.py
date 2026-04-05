"""Logging configuration for Arcane.

Call ``configure_logging()`` once at process startup (CLI entry point or MCP
server).  Library code just calls ``logging.getLogger(__name__)`` — the root
handler is configured externally.
"""

from __future__ import annotations

import logging
import os
import sys


def configure_logging(verbose: bool = False) -> None:
    """Configure the root ``arcane`` logger.

    Args:
        verbose: When *True* emit DEBUG messages; otherwise INFO and above.
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Honour ARCANE_LOG_LEVEL env-var override (e.g. ARCANE_LOG_LEVEL=DEBUG)
    env_level = os.environ.get("ARCANE_LOG_LEVEL", "").upper()
    if env_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        level = getattr(logging, env_level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(levelname)s [%(name)s] %(message)s",
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger("arcane")
    logger.setLevel(level)
    # Avoid duplicate handlers if called multiple times (e.g. in tests)
    if not logger.handlers:
        logger.addHandler(handler)
    else:
        logger.handlers[0].setLevel(level)
        logger.setLevel(level)
