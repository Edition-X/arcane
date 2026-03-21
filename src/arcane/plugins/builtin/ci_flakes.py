"""CI flake detection intelligence plugin."""

from __future__ import annotations

from typing import Any


class CIFlakeDetector:
    name = "ci_flakes"

    def analyze(self, project: str) -> list[dict[str, Any]]:
        return []
