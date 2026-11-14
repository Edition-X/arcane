"""E2E: memory_save and memory_update warn when a decision's reasoning is thin."""

from __future__ import annotations

from typing import Any

from tests.e2e.conftest import Arcane, Client

OPTIONS = "Context: the old path lost data.\nOptions considered: keep it, or move to the new one. Chose the new one."
WHY = "The old path lost data on restart"
CODES = ("no_why", "why_only_says_who_asked", "no_options")


def codes(result: dict[str, Any]) -> list[str]:
    """Name each warning by its code, or no_details for the details warning; anything else fails."""
    named = []
    for warning in result.get("warnings", []):
        code = next((c for c in CODES if warning.startswith(f"{c}:")), None)
        if code is None:
            assert "should include details" in warning, warning
            code = "no_details"
        named.append(code)
    return named


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
            "good": await decision(c, 2, why=WHY, details=OPTIONS),
        }

    out = arcane.run(scenario)

    assert codes(out["bare"]) == ["no_why"]
    assert "search results show why but not details" in out["bare"]["warnings"][0]
    assert "memory_update" in out["bare"]["warnings"][0]
    assert out["good"]["warnings"] == []
    assert out["bare"]["action"] == "created"  # a warning never blocks the save


def test_a_why_that_only_says_who_asked_warns(arcane: Arcane) -> None:
    thin = {
        "user": "User asked for the cache layer to be rewritten",
        "restated": "User asked for it because the user asked for it",
        "first_name": "Lukas asked for the cache layer to be rewritten",
        "adverb": "User explicitly asked for the cache layer to be rewritten",
        "has_asked": "The user has asked for the cache layer to be rewritten",
        "present": "User wants the cache layer rewritten",
    }
    fine = {
        "reason": "User asked for the cache rewrite because the old path lost data on restart",
        "purpose": "User requested the rewrite so the cache survives restarts without a rebuild",
        "to_reduce": "User asked for the cache layer to reduce memory use on small laptops",
        "to_cut": "User asked for a rewrite to cut startup time on small laptops",
        "to_keep": "User asked for a rewrite to keep the cache small on laptops",
        "to_make": "User asked for a rewrite to make restarts safe for the cache",
        "second_sentence": "User asked for the rewrite. The old path lost data on restart.",
        "colon": "User asked: the old path lost data on restart",
        "semicolon": "User asked for the rewrite; the old path lost data on restart",
        "dash": "User asked for the rewrite - the old path lost data on restart",
        "no_who": WHY,
        "name_reason": "Lukas asked for the rewrite because the old path lost data on restart",
        "name_other_verb": "Lukas wanted the cache layer rewritten",
        "benchmarks": "Benchmarks told us sqlite-vec was three times faster",
        "customers": "Customers wanted sub-second recall on a laptop",
        "we": "We wanted the cache layer rewritten",
        "we_asked": "We asked for the cache layer to be rewritten",
        "we_reason": "We wanted the cache layer rewritten to avoid losing data on restart",
        "i": "I wanted the cache layer rewritten",
    }

    async def scenario(c: Client) -> dict[str, Any]:
        return {
            name: await decision(c, n, why=why, details=OPTIONS)
            for n, (name, why) in enumerate({**thin, **fine}.items(), start=10)
        }

    out = arcane.run(scenario)

    for name in thin:
        assert codes(out[name]) == ["why_only_says_who_asked"], name
    assert "memory_update" in out["user"]["warnings"][0]
    for name in fine:
        assert out[name]["warnings"] == [], name


def test_a_decision_without_options_warns(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        return {
            "missing": await decision(c, 60, why=WHY, details="Context: the old path lost data. Decision: new path."),
            "steps": await decision(c, 61, why=WHY, details="Steps:\n1. Install the new path\n2. Remove the old one"),
            "present": await decision(c, 62, why=WHY, details=OPTIONS),
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
    assert codes(out["steps"]) == ["no_options"]  # a numbered list is not a list of options
    assert out["present"]["warnings"] == []
    assert out["bug"]["warnings"] == []  # options are asked of decisions only


def test_one_warning_per_gap(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        nothing = await decision(c, 70)
        details_only = await decision(c, 71, details="Context: the old path lost data.")
        return {
            "nothing": nothing,
            "details_only": details_only,
            "other_category": await c.call(
                "memory_save", title="Cache notes", what="How the cache is laid out", category="context"
            ),
            "found": {
                "nothing": await c.call("memory_search", query="Decision number 70", detail="minimal"),
                "details_only": await c.call("memory_search", query="Decision number 71", detail="minimal"),
            },
            "body": await c.call("memory_details", memory_id=details_only["id"]),
        }

    out = arcane.run(scenario)

    # No details at all: the no-details warning and no_why, but not also no_options.
    assert codes(out["nothing"]) == ["no_details", "no_why"]
    assert codes(out["details_only"]) == ["no_why", "no_options"]
    assert "reasoning into why" in out["details_only"]["warnings"][0]
    assert out["other_category"]["warnings"] == []
    # Warned saves are saved, not refused.
    for name in ("nothing", "details_only"):
        assert out[name]["action"] == "created"
        assert out[name]["id"] in [m["id"] for m in out["found"][name]]
    assert out["body"]["body"] == "Context: the old path lost data."


def test_update_rechecks_only_when_why_or_details_change(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        saved = await decision(
            c, 40, why="User asked for the cache rewrite", details="Context: the old path lost data."
        )
        mid = saved["id"]
        out: dict[str, Any] = {"saved": saved}
        out["tags_only"] = await c.call("memory_update", memory_id=mid, tags=["cache"])
        out["what_only"] = await c.call("memory_update", memory_id=mid, what="Chose approach 40 again")
        out["why_fixed"] = await c.call(
            "memory_update", memory_id=mid, why="User asked for it because the old path lost data on restart"
        )
        out["all_fixed"] = await c.call(
            "memory_update", memory_id=mid, details_append="Options considered: keep it, or move to the new one."
        )
        out["details"] = await c.call("memory_details", memory_id=mid)
        return out

    out = arcane.run(scenario)
    mid = out["saved"]["id"]

    assert codes(out["saved"]) == ["why_only_says_who_asked", "no_options"]
    assert out["tags_only"] == {
        "updated": True,
        "memory_id": mid,
    }  # still thin, but nothing about why or details changed
    assert out["what_only"] == {"updated": True, "memory_id": mid}
    assert codes(out["why_fixed"]) == ["no_options"]
    assert out["all_fixed"] == {"updated": True, "memory_id": mid}  # nothing applies: no key
    assert "Options considered" in out["details"]["body"]


def test_a_same_titled_save_reports_the_stored_memory(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        out: dict[str, Any] = {"first": await decision(c, 50, why=WHY, details=OPTIONS)}
        # Same title, nothing about reasoning: the stored why and options stay in place.
        out["bare_again"] = await decision(c, 50)
        out["stored"] = await c.call("memory_search", query="Decision number 50", detail="full")
        out["thin_first"] = await decision(c, 51, why="User asked for the cache layer to be rewritten")
        # Same title again, now complete: the stored memory is fixed, so nothing applies.
        out["fixed_again"] = await decision(c, 51, why=WHY, details=OPTIONS)
        return out

    out = arcane.run(scenario)

    assert out["first"]["warnings"] == []
    assert out["bare_again"]["action"] == "updated"
    assert out["bare_again"]["id"] == out["first"]["id"]
    assert out["bare_again"]["warnings"] == []
    assert out["stored"][0]["why"] == WHY
    assert codes(out["thin_first"]) == ["no_details", "why_only_says_who_asked"]
    assert out["fixed_again"]["action"] == "updated"
    assert out["fixed_again"]["warnings"] == []
