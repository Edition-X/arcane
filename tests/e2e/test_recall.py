"""E2E recall: a synthetic corpus, asked the way people and agents ask, scored as counts against floors.

The real ``arcane mcp`` server runs against a temp store, with only Ollama faked
(hashed bag-of-words vectors). The corpus is invented: three orgs, five projects,
answer memories with look-alike distractors in the same project, in a sibling
project and in another org, and memories a newer one replaced. Each case has one
known answer; each measure is the number of cases that find it, held to a floor.

Run with ``-rA`` to see the counts of a green run; a red run prints them in the
assertion message. Each floor is what the code scores today, less one case where a
shared word could tip a single case either way; the comments on the floors say which.

The fake's vectors carry no meaning, so this holds keyword search, ranking, widening,
indexing and the call to the embedder. It cannot show a regression in how well real
embeddings match a paraphrase.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.e2e.conftest import Client, FakeOllama, make_arcane, use_fake_ollama

ORG = "acme"
HOME_PROJECT = "widget"  # the repo the server runs in
EMPTY_PROJECT = "notes"  # in the org, holds nothing: the question asked from a directory with no memories
SIBLING_PROJECT = "gadget"  # in the org, populated with look-alikes


@dataclass
class Answer:
    title: str
    what: str
    why: str
    question: str  # how a person asks
    keywords: str  # how an agent turns it into a query
    details: str = ""
    related_files: list[str] = field(default_factory=list)


# Ten answers in widget. Each question shares only some words with its memory, as real ones do.
ANSWERS = [
    Answer(
        "Retry jobs with jittered backoff",
        "Queue workers retry a failed job after a random, growing delay",
        "A fixed delay made every worker hit the broker together after an outage",
        "why do queue workers retry a failed job after a random delay",
        "jittered backoff retry workers",
    ),
    Answer(
        "Sessions live in redis",
        "User sessions are stored in redis, not in the database",
        "Login latency was dominated by the sessions table in postgres",
        "why are user sessions stored in redis not postgres",
        "session store redis",
    ),
    Answer(
        "Pin the base image by digest",
        "The dockerfile names the base image by its sha256 digest",
        "A moved tag changed the image under us and broke a release",
        "why does the dockerfile pin the base image by digest",
        "base image digest pin",
    ),
    Answer(
        "Feature flags are read once",
        "Feature flags are loaded when the service starts and never refreshed",
        "Reading them on every request cost three milliseconds",
        "why are feature flags loaded when the service starts",
        "feature flags loaded service starts",
    ),
    Answer(
        "Invoices round half to even",
        "Invoice totals use bankers rounding",
        "Finance audited the totals and a cent drifted over a month of invoices",
        "why do invoice totals use bankers rounding",
        "invoice rounding half even",
    ),
    Answer(
        "Webhooks carry an HMAC signature",
        "Incoming webhooks must send a signature header made with a rotating secret",
        "Anyone who found the endpoint could post fake events",
        "why do incoming webhooks send a signature header",
        "webhook HMAC signature secret rotation",
    ),
    Answer(
        "Backups run at 02:00 UTC",
        "The nightly database backup starts at two in the morning",
        "Traffic is lowest then and the dump does not slow checkout",
        "why does the database backup start at two in the morning",
        "database backup nightly traffic",
    ),
    Answer(
        "CSV export streams rows",
        "The csv export writes rows as it reads them",
        "A two million row export ran the pod out of memory",
        "why does the csv export write rows as it reads them",
        "csv export streaming memory",
    ),
    Answer(
        "Search index rebuilds nightly",
        "The search index is rebuilt by a nightly job, not on every write",
        "Reindexing on write doubled the latency of every save",
        "why is the search index rebuilt by a nightly job",
        "search index nightly rebuild",
    ),
    Answer(
        "Rate limit is per API key",
        "Requests are throttled per API key rather than per client address",
        "Customers behind one office address were blocked together",
        "why is rate limiting keyed on the api key rather than the client address",
        "rate limit api key",
    ),
]

# Words that appear only in details, asked back as a phrase from them.
DETAIL_ONLY = [
    (
        "Connection pool sizing",
        "Sized the database pool",
        "pgbouncer transaction pooling saturates near 400 connections",
    ),
    (
        "Image resize worker",
        "Moved resizing off the request path",
        "libvips beats imagemagick on the 40 megapixel scans",
    ),
    (
        "Audit log retention",
        "Audit rows are kept for a year",
        "legal hold ticket LEG-2291 forbids deleting before March",
    ),
    (
        "Cursor pagination",
        "List endpoints page by cursor",
        "offset paging skipped rows when tamarind imports ran concurrently",
    ),
    (
        "Timezone handling",
        "Timestamps are stored in UTC",
        "the sydney daylight change corrupted the nightly settlement window",
    ),
]

# Memories found by the path they touched; each has a sibling file in a look-alike path.
BY_PATH = [
    ("Handler rewrite", "src/widget/handlers/orders.py", "src/widget/handlers/orders_v1.py"),
    ("Config loader change", "src/widget/config/loader.py", "src/widget/config/loader_test.py"),
    ("Billing rounding fix", "src/widget/billing/rounding.py", "src/widget/billing/invoice.py"),
    ("Migration for tenants", "migrations/0042_add_tenants.sql", "migrations/0041_add_teams.sql"),
    ("Deploy script hardening", "deploy/release.sh", "deploy/rollback.sh"),
]

# (old title, new title, question): the new memory replaces the old, and the question matches both.
REPLACED = [
    ("Cache TTL is one hour", "Cache TTL is five minutes", "what is the cache ttl"),
    ("Deploys go through jenkins", "Deploys go through github actions", "what do deploys go through"),
    ("Logs ship to papertrail", "Logs ship to loki", "where do logs ship to"),
    ("Passwords hashed with sha1", "Passwords hashed with argon2", "how are passwords hashed"),
]

# In widget, sharing words with the answers but answering something else.
WIDGET_DISTRACTORS = [
    ("Retry policy for the email sender", "The mailer retries a bounced email three times", "bounces are common"),
    ("Redis eviction policy", "Redis evicts least recently used keys", "memory is capped"),
    ("Session cookie lifetime", "The session cookie lasts a day", "security review"),
    ("Docker layer caching", "CI caches docker layers between builds", "builds were slow"),
    ("Webhook payload versioning", "Webhook payloads carry a version field", "consumers upgrade late"),
    ("Backup restore drill", "A restore from backup is tried each quarter", "an untested backup is a hope"),
    ("Feature flag naming", "Feature flags are named after the team and the feature", "flags were hard to find"),
    ("Invoice PDF layout", "Invoice pdfs use the shared header", "branding"),
]

# In the sibling project: the same topics from another team, never the answer to a widget question.
SIBLING_MEMORIES = [
    ("Gadget job retries", "Gadget jobs retry once and then page someone", "pages are cheaper than backlog"),
    ("Gadget session timeout", "Gadget sessions end after ten idle minutes", "kiosk mode"),
    ("Gadget image tags", "Gadget images use the git sha as the tag", "traceability"),
    ("Gadget flags dashboard", "Gadget shows flags on the ops dashboard", "visibility"),
    ("Gadget invoice export", "Gadget exports invoices nightly", "accounting asked"),
    ("Gadget webhook retries", "Gadget webhooks retry for a day", "partners are slow"),
    ("Gadget backup bucket", "Gadget backups go to a second region", "disaster recovery"),
    ("Gadget csv import", "Gadget imports csv files through a queue", "bulk onboarding"),
    ("Gadget search weights", "Gadget boosts exact title matches in search", "relevance"),
    ("Gadget api quotas", "Gadget grants partners a daily api quota", "contracts"),
]

# Other orgs reuse the same words; none of it may reach an acme search.
OTHER_ORG_MEMORIES = [
    ("beta", "ledger", "Sessions live in redis", "Ledger keeps sessions in redis too", "copied from acme"),
    ("beta", "ledger", "Feature flags are read once", "Ledger loads flags at start", "same pattern"),
    ("beta", "ledger", "Rate limit is per API key", "Ledger throttles by api key", "same pattern"),
    ("beta", "ledger", "Backups run at 02:00 UTC", "Ledger backs up at two", "same pattern"),
    ("beta", "ledger", "CSV export streams rows", "Ledger streams csv", "same pattern"),
    ("gamma", "forge", "Pin the base image by digest", "Forge pins images by digest", "same pattern"),
    ("gamma", "forge", "Retry jobs with jittered backoff", "Forge retries with jitter", "same pattern"),
    ("gamma", "forge", "Invoices round half to even", "Forge rounds invoices", "same pattern"),
]

# How far down the hits each answer may sit. Today every recall case ranks first, so the
# answer must be the first hit; the floors' slack allows for a look-alike tipping one case.
TOP_IN_PROJECT = 1
TOP_WIDENED = 1
TOP_EXACT = 1

# Floors: the count the code scores today, less one case where a shared word could tip a
# single case.
# Questions and keywords: 10/10 today. A look-alike in the same project or a sibling could
# push one answer down a place or two without it being a regression, so one case of slack.
FLOOR_IN_PROJECT_QUESTION = 9
FLOOR_IN_PROJECT_KEYWORDS = 9
# Asked from an empty project, or a populated one that matches too little, the search must widen
# to the org: 10/10 today, one case of slack for the same reason.
FLOOR_OTHER_PROJECT = 9
FLOOR_SIBLING_PROJECT = 9
# Words only in details, and a memory's own file path, each match one memory outright and the
# distractors share none of them, so there is no reason to lose a case: no slack.
FLOOR_DETAILS_ONLY = 5
FLOOR_BY_PATH = 5
# A replaced memory is halved in score and gets no whole-query bonus. With the question as
# asked, both memories hold every key word, and either of the two alone puts the new one
# first: 4/4, no slack. With a word added that neither holds, neither gets the bonus and only
# the halving separates them: 3/4 today ("where do logs ship to today" still ranks the old
# one first).
FLOOR_REPLACED_BELOW_NEW = 4
FLOOR_REPLACED_BELOW_NEW_NO_BONUS = 3


IN_PROJECT_QUESTION = f"in-project question, top {TOP_IN_PROJECT}"
IN_PROJECT_KEYWORDS = f"in-project keywords, top {TOP_IN_PROJECT}"
OTHER_PROJECT = f"other project (empty), top {TOP_WIDENED}"
SIBLING_PROJECT = f"sibling project (populated), top {TOP_WIDENED}"
DETAILS_ONLY = f"phrase only in details, top {TOP_EXACT}"
BY_OWN_PATH = f"own related file path, top {TOP_EXACT}"
REPLACED_BELOW_NEW = "replaced memory ranks below its replacement"
REPLACED_BELOW_NEW_NO_BONUS = "replaced memory ranks below its replacement, no whole-query bonus"


@dataclass
class Scores:
    """Each measure's (found, cases), and what the server saw while scoring."""

    counts: dict[str, tuple[int, int]]
    embedded: list[str]  # every prompt the fake Ollama received after seeding
    searches: list[str]  # every query issued, in order
    org_leaks: list[str]


def _hits(result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = result["results"] if isinstance(result, dict) else result  # none found: a dict
    return rows


async def _seed(c: Client) -> None:
    for a in ANSWERS:
        await c.call(
            "memory_save",
            title=a.title,
            what=a.what,
            why=a.why,
            details=f"Decided in the {a.title.lower()} review.",
            related_files=[f"src/widget/{a.title.split()[0].lower()}.py"],
        )
    for title, what, why in WIDGET_DISTRACTORS:
        await c.call("memory_save", title=title, what=what, why=why)
    for title, what, details in DETAIL_ONLY:
        await c.call("memory_save", title=title, what=what, details=details)
    for title, path, sibling_path in BY_PATH:
        await c.call("memory_save", title=title, what="Changed one file", related_files=[path])
        await c.call(
            "memory_save", title=f"{title} (sibling file)", what="Changed another file", related_files=[sibling_path]
        )
    for old, new, question in REPLACED:
        # The old memory also quotes the question, so both memories hold every key word of it.
        saved = await c.call("memory_save", title=old, what=f"{old}. {question}", why="the first choice")
        await c.call(
            "memory_save", title=new, what=f"{new} for the service", why="the later choice", supersedes=saved["id"]
        )
    for title, what, why in SIBLING_MEMORIES:
        await c.call("memory_save", title=title, what=what, why=why, project=SIBLING_PROJECT, org=ORG)
    for org, project, title, what, why in OTHER_ORG_MEMORIES:
        await c.call("memory_save", title=title, what=what, why=why, project=project, org=org)


async def _score(c: Client, ollama: FakeOllama) -> Scores:
    searches: list[str] = []
    leaks: list[str] = []

    async def search(query: str, **scope: str) -> list[dict[str, Any]]:
        searches.append(query)
        hits = _hits(await c.call("memory_search", query=query, limit=10, **scope))
        leaks.extend(f"{query!r} -> {h['org']}/{h['project']}/{h['title']}" for h in hits if h["org"] != ORG)
        return hits

    def rank(hits: list[dict[str, Any]], title: str) -> int | None:
        return next((i for i, h in enumerate(hits, 1) if h["title"] == title), None)

    counts: dict[str, tuple[int, int]] = {}
    ollama.prompts.clear()

    async def found(cases: list[tuple[str, str]], within: int, **scope: str) -> int:
        """How many (query, title) cases have the title in the top *within* hits."""
        total = 0
        for query, title in cases:
            r = rank(await search(query, **scope), title)
            if r is not None and r <= within:
                total += 1
        return total

    questions = [(a.question, a.title) for a in ANSWERS]
    n = len(ANSWERS)
    counts[IN_PROJECT_QUESTION] = (await found(questions, TOP_IN_PROJECT), n)
    keywords = [(a.keywords, a.title) for a in ANSWERS]
    counts[IN_PROJECT_KEYWORDS] = (await found(keywords, TOP_IN_PROJECT), n)
    counts[OTHER_PROJECT] = (await found(questions, TOP_WIDENED, project=EMPTY_PROJECT, org=ORG), n)
    counts[SIBLING_PROJECT] = (await found(questions, TOP_WIDENED, project=SIBLING_PROJECT, org=ORG), n)
    phrases = [(" ".join(details.split()[:5]), title) for title, _, details in DETAIL_ONLY]
    counts[DETAILS_ONLY] = (await found(phrases, TOP_EXACT), len(DETAIL_ONLY))
    counts[BY_OWN_PATH] = (await found([(path, title) for title, path, _ in BY_PATH], TOP_EXACT), len(BY_PATH))

    async def new_first(query_suffix: str) -> int:
        """How many replacements rank above the memory they replaced."""
        total = 0
        for old, new, question in REPLACED:
            hits = await search(question + query_suffix)
            new_rank, old_rank = rank(hits, new), rank(hits, old)
            if new_rank is not None and (old_rank is None or new_rank < old_rank):
                total += 1
        return total

    counts[REPLACED_BELOW_NEW] = (await new_first(""), len(REPLACED))
    counts[REPLACED_BELOW_NEW_NO_BONUS] = (await new_first(" today"), len(REPLACED))
    return Scores(counts, list(ollama.prompts), searches, leaks)


@pytest.fixture(scope="module")
def scores(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Scores]:
    ollama = FakeOllama()
    arcane = make_arcane(tmp_path_factory.mktemp("recall"))
    use_fake_ollama(arcane, ollama)

    async def scenario(c: Client) -> Scores:
        await _seed(c)
        return await _score(c, ollama)

    try:
        yield arcane.run(scenario)
    finally:
        ollama.stop()


def _check(scores: Scores, measure: str, floor: int) -> None:
    got, total = scores.counts[measure]
    line = f"recall {measure}: {got}/{total} (floor {floor})"
    print(line)
    assert got >= floor, line


def test_a_natural_question_finds_the_memory_in_its_own_project(scores: Scores) -> None:
    _check(scores, IN_PROJECT_QUESTION, FLOOR_IN_PROJECT_QUESTION)


def test_an_agents_keywords_find_the_memory_in_its_own_project(scores: Scores) -> None:
    _check(scores, IN_PROJECT_KEYWORDS, FLOOR_IN_PROJECT_KEYWORDS)


def test_the_question_asked_from_an_empty_project_widens_to_the_org(scores: Scores) -> None:
    _check(scores, OTHER_PROJECT, FLOOR_OTHER_PROJECT)


def test_the_question_asked_from_a_populated_sibling_still_finds_it(scores: Scores) -> None:
    _check(scores, SIBLING_PROJECT, FLOOR_SIBLING_PROJECT)


def test_a_phrase_only_in_details_finds_the_memory(scores: Scores) -> None:
    _check(scores, DETAILS_ONLY, FLOOR_DETAILS_ONLY)


def test_a_memorys_own_file_path_finds_it(scores: Scores) -> None:
    _check(scores, BY_OWN_PATH, FLOOR_BY_PATH)


def test_a_replaced_memory_ranks_below_its_replacement(scores: Scores) -> None:
    _check(scores, REPLACED_BELOW_NEW, FLOOR_REPLACED_BELOW_NEW)


def test_a_word_neither_memory_holds_mostly_ranks_the_replacement_first(scores: Scores) -> None:
    _check(scores, REPLACED_BELOW_NEW_NO_BONUS, FLOOR_REPLACED_BELOW_NEW_NO_BONUS)


def test_no_search_reaches_another_org(scores: Scores) -> None:
    line = f"recall hits from another org: {len(scores.org_leaks)} in {len(scores.searches)} searches (must be 0)"
    print(line)
    assert not scores.org_leaks, "\n".join([line, *scores.org_leaks])


def test_every_search_embeds_its_query_once(scores: Scores) -> None:
    # The embedding model runs for every query, however many keyword matches there are;
    # a search that skips it falls back on keywords alone.
    embedded = len(scores.embedded)
    searches = len(scores.searches)
    line = f"recall query embeds: {embedded} for {searches} searches (must be equal)"
    print(line)
    assert embedded == searches, line
