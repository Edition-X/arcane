"""Regression coverage for secret redaction at persistence boundaries."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from arcane.domain.models import RawMemoryInput
from arcane.services.ingestion import IngestionService
from arcane.services.intelligence import IntelligenceService
from arcane.services.journey import JourneyService
from arcane.services.memory import MemoryService

OPENAI_TOKEN = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
GITHUB_TOKEN = "github_pat_abcdefghijklmnopqrstuvwxyz0123456789"
CUSTOM_SECRET = "internal-secret-123"


def _assert_redacted(value: object) -> None:
    serialized = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    assert OPENAI_TOKEN not in serialized
    assert GITHUB_TOKEN not in serialized


def test_repositories_redact_known_secrets_in_all_persisted_fields(
    memory_repo, artifact_repo, journey_repo, insight_repo
):
    now = datetime.now(timezone.utc).isoformat()
    memory_id = str(uuid.uuid4())
    memory_repo.insert(
        {
            "id": memory_id,
            "title": f"Title {OPENAI_TOKEN}",
            "what": f"What {GITHUB_TOKEN}",
            "why": OPENAI_TOKEN,
            "impact": GITHUB_TOKEN,
            "tags": [OPENAI_TOKEN],
            "project": "project",
            "source": OPENAI_TOKEN,
            "related_files": [f"/{GITHUB_TOKEN}/config"],
            "file_path": f"/{OPENAI_TOKEN}/session.md",
            "section_anchor": GITHUB_TOKEN,
            "created_at": now,
            "updated_at": now,
            "metadata": {"token": OPENAI_TOKEN},
        },
        details=GITHUB_TOKEN,
    )
    artifact_id = str(uuid.uuid4())
    artifact_repo.insert(
        {
            "id": artifact_id,
            "artifact_type": "commit",
            "external_id": OPENAI_TOKEN,
            "title": GITHUB_TOKEN,
            "url": f"https://example.test/{OPENAI_TOKEN}",
            "raw_data": {"nested": [GITHUB_TOKEN]},
            "project": "project",
            "created_at": now,
        }
    )
    journey_id = str(uuid.uuid4())
    journey_repo.insert(
        {
            "id": journey_id,
            "title": OPENAI_TOKEN,
            "project": "project",
            "status": "active",
            "started_at": now,
            "summary": GITHUB_TOKEN,
            "linear_issue_id": OPENAI_TOKEN,
            "created_at": now,
            "updated_at": now,
        }
    )
    insight_id = str(uuid.uuid4())
    insight_repo.insert(
        {
            "id": insight_id,
            "insight_type": "test",
            "title": OPENAI_TOKEN,
            "body": GITHUB_TOKEN,
            "project": "project",
            "metadata": {"token": OPENAI_TOKEN},
            "created_at": now,
        }
    )

    _assert_redacted(memory_repo.get(memory_id))
    _assert_redacted(memory_repo.get_details(memory_id))
    _assert_redacted(artifact_repo.get(artifact_id))
    _assert_redacted(journey_repo.get(journey_id))
    _assert_redacted(insight_repo.list_all(project="project"))


def test_memory_save_and_update_redact_custom_patterns_before_embedding_and_markdown(container, tmp_path):
    class CapturingEmbedder:
        def __init__(self) -> None:
            self.inputs: list[str] = []

        def embed(self, text: str) -> list[float]:
            self.inputs.append(text)
            return [0.1] * 3

    embedder = CapturingEmbedder()
    container._embedding_provider = embedder
    container._ignore_patterns = [r"internal-secret-\d+"]
    service = MemoryService(container)

    created = service.save(
        RawMemoryInput(
            title=f"Title {OPENAI_TOKEN}",
            what=CUSTOM_SECRET,
            why=GITHUB_TOKEN,
            impact=OPENAI_TOKEN,
            tags=[GITHUB_TOKEN],
            source=CUSTOM_SECRET,
            related_files=[f"/{CUSTOM_SECRET}/config"],
            details=GITHUB_TOKEN,
        ),
        project="project",
    )
    assert created["action"] == "created"
    stored = container.memory_repo.get(created["id"])
    _assert_redacted(stored)
    assert CUSTOM_SECRET not in json.dumps(stored)
    assert CUSTOM_SECRET not in container.memory_repo.get_details(created["id"])["body"]
    assert all(
        OPENAI_TOKEN not in value and GITHUB_TOKEN not in value and CUSTOM_SECRET not in value
        for value in embedder.inputs
    )
    assert CUSTOM_SECRET not in (tmp_path / "vault" / "project").glob("*.md").__next__().read_text()

    assert service.update(
        created["id"],
        what=OPENAI_TOKEN,
        why=CUSTOM_SECRET,
        impact=GITHUB_TOKEN,
        tags=[CUSTOM_SECRET],
        details_append=OPENAI_TOKEN,
    )
    updated = container.memory_repo.get(created["id"])
    _assert_redacted(updated)
    assert CUSTOM_SECRET not in json.dumps(updated)
    assert all(
        OPENAI_TOKEN not in value and GITHUB_TOKEN not in value and CUSTOM_SECRET not in value
        for value in embedder.inputs
    )


def test_services_apply_custom_patterns_to_artifacts_journeys_and_insights(container):
    class ArtifactPlugin:
        name = "artifact"

        def ingest(self, project, since=None):
            return [
                {
                    "id": str(uuid.uuid4()),
                    "artifact_type": "commit",
                    "external_id": "commit-id",
                    "title": CUSTOM_SECRET,
                    "raw_data": {"token": CUSTOM_SECRET},
                    "project": project,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ]

    class InsightPlugin:
        name = "insight"

        def analyze(self, project):
            return [
                {
                    "id": str(uuid.uuid4()),
                    "insight_type": "test",
                    "title": CUSTOM_SECRET,
                    "body": CUSTOM_SECRET,
                    "metadata": {"token": CUSTOM_SECRET},
                    "project": project,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ]

    container._ignore_patterns = [r"internal-secret-\d+"]
    journey = JourneyService(container).start(CUSTOM_SECRET, project="project", linear_issue_id=CUSTOM_SECRET)
    assert JourneyService(container).update(journey["id"], summary=CUSTOM_SECRET)
    IngestionService(container).run_plugin(ArtifactPlugin(), project="project")
    IntelligenceService(container).run_plugin(InsightPlugin(), project="project")

    assert CUSTOM_SECRET not in json.dumps(JourneyService(container).get(journey["id"]))
    assert CUSTOM_SECRET not in json.dumps(container.artifact_repo.list_all(project="project"))
    assert CUSTOM_SECRET not in json.dumps(container.insight_repo.list_all(project="project"))
