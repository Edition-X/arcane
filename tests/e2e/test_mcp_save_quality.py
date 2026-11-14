"""E2E: memory_save and memory_update warn when a decision's reasoning is thin."""

from __future__ import annotations

from typing import Any

from tests.e2e.conftest import Arcane, Client

OPTIONS = "Context: the old path lost data.\nOptions considered: keep it, or move to the new one. Chose the new one."


def codes(result: dict[str, Any]) -> list[str]:
    """The warning codes in a save or update reply; the no-details warning has none."""
    return [w.split(":")[0] if ":" in w.split(" ")[0] else "no_details" for w in result.get("warnings", [])]


async def decision(c: Client, n: int, **fields: Any) -> dict[str, Any]:
    return await c.call(
        "memory_save",
        title=f"Decision number {n} about the cache layer",
        what=f"Chose approach {n} for the cache layer",
        category="decision",
        **fields,
    )


def test_a_decision_without_why_warns(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        return {
            "bare": await decision(c, 1, details=OPTIONS),
            "good": await decision(c, 2, why="The old path lost data on restart", details=OPTIONS),
        }

    out = arcane.run(scenario)

    assert codes(out["bare"]) == ["no_why"]
    assert "search results show why but not details" in out["bare"]["warnings"][0]
    assert "memory_update" in out["bare"]["warnings"][0]
    assert out["good"]["warnings"] == []
    assert out["bare"]["action"] == "created"  # a warning never blocks the save


def test_a_why_that_only_says_who_asked_warns(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        asked = {
            "thin": "User asked for the cache layer to be rewritten",
            "restated": "User asked for it because the user asked for it",
            "reason": "User asked for the cache rewrite because the old path lost data on restart",
            "purpose": "User requested the rewrite so the cache survives restarts without a rebuild",
            "second_sentence": "User asked for the rewrite. The old path lost data on restart.",
            "no_who": "The old path lost data on restart",
        }
        return {
            name: await decision(c, n, why=why, details=OPTIONS)
            for n, (name, why) in enumerate(asked.items(), start=10)
        }

    out = arcane.run(scenario)

    assert codes(out["thin"]) == ["why_only_says_who_asked"]
    assert "memory_update" in out["thin"]["warnings"][0]
    assert codes(out["restated"]) == ["why_only_says_who_asked"]
    for name in ("reason", "purpose", "second_sentence", "no_who"):
        assert out[name]["warnings"] == [], name


def test_a_decision_without_options_warns(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        why = "The old path lost data on restart"
        return {
            "missing": await decision(c, 20, why=why, details="Context: the old path lost data. Decision: new path."),
            "present": await decision(c, 21, why=why, details=OPTIONS),
            "bug": await c.call(
                "memory_save",
                title="Cache lost data on restart",
                what="Cache dropped entries on restart",
                category="bug",
                details="Root cause: the flush ran after shutdown.",
            ),
        }

    out = arcane.run(scenario)

    assert codes(out["missing"]) == ["no_options"]
    assert "memory_update" in out["missing"]["warnings"][0]
    assert out["present"]["warnings"] == []
    assert out["bug"]["warnings"] == []  # options are asked of decisions only


def test_one_warning_per_gap(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        return {
            "nothing": await decision(c, 30),
            "details_only": await decision(c, 31, details="Context: the old path lost data."),
            "other_category": await c.call(
                "memory_save", title="Cache notes", what="How the cache is laid out", category="context"
            ),
        }

    out = arcane.run(scenario)

    # No details at all: the no-details warning and no_why, but not also no_options.
    assert codes(out["nothing"]) == ["no_details", "no_why"]
    assert codes(out["details_only"]) == ["no_why", "no_options"]
    assert "reasoning into why" in out["details_only"]["warnings"][0]
    assert out["other_category"]["warnings"] == []


def test_update_rechecks_and_returns_what_still_applies(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        saved = await decision(
            c, 40, why="User asked for the cache rewrite", details="Context: the old path lost data."
        )
        mid = saved["id"]
        out: dict[str, Any] = {"saved": saved}
        out["unrelated"] = await c.call("memory_update", memory_id=mid, tags=["cache"])
        out["why_fixed"] = await c.call(
            "memory_update", memory_id=mid, why="User asked for it because the old path lost data on restart"
        )
        out["all_fixed"] = await c.call(
            "memory_update", memory_id=mid, details_append="Options considered: keep it, or move to the new one."
        )
        out["details"] = await c.call("memory_details", memory_id=mid)
        return out

    out = arcane.run(scenario)

    assert codes(out["saved"]) == ["why_only_says_who_asked", "no_options"]
    assert codes(out["unrelated"]) == ["why_only_says_who_asked", "no_options"]
    assert codes(out["why_fixed"]) == ["no_options"]
    assert out["all_fixed"] == {"updated": True, "memory_id": out["saved"]["id"]}  # nothing applies: no key
    assert "Options considered" in out["details"]["body"]
