"""Integration tests for concurrent writes to a shared Arcane vault."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from arcane.domain.models import RawMemoryInput
from arcane.infra.db.connection import BUSY_TIMEOUT_MS, Database
from arcane.infra.db.memory_repo import MemoryRepository
from arcane.infra.db.schema import create_schema
from arcane.services.container import create_container
from arcane.services.memory import MemoryService
from tests.conftest import make_memory_dict


class _FixedEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        return [0.1] * 8


def _save_memory_worker(home: str, index: int, start: multiprocessing.synchronize.Event, results) -> None:
    try:
        with create_container(home) as container:
            container._embedding_provider = _FixedEmbeddingProvider()
            start.wait(timeout=15)
            MemoryService(container).save(
                RawMemoryInput(title=f"Concurrent memory {index}", what=f"Worker {index} completed"),
                project="shared-project",
                org="test-org",
            )
        results.put(None)
    except Exception as exc:  # pragma: no cover - asserted by parent process
        results.put(repr(exc))


def test_database_uses_wal_and_explicit_busy_timeout(tmp_path):
    db = Database(str(tmp_path / "index.db"))
    try:
        assert db.fetchone("PRAGMA journal_mode")["journal_mode"] == "wal"
        assert db.fetchone("PRAGMA busy_timeout")["timeout"] == BUSY_TIMEOUT_MS
    finally:
        db.close()


def test_transaction_rolls_back_repository_commit(tmp_path):
    db = Database(str(tmp_path / "index.db"))
    create_schema(db)
    repo = MemoryRepository(db)
    try:
        with pytest.raises(RuntimeError, match="force rollback"):
            with db.transaction():
                repo.insert(make_memory_dict())
                raise RuntimeError("force rollback")

        assert repo.count() == 0
    finally:
        db.close()


def test_memory_save_rolls_back_when_vector_storage_fails(container, monkeypatch):
    service = MemoryService(container)

    def fail_vector_store(*_args, **_kwargs):
        raise RuntimeError("vector store failed")

    monkeypatch.setattr(container.memory_repo, "insert_vector", fail_vector_store)

    with pytest.raises(RuntimeError, match="vector store failed"):
        service.save(RawMemoryInput(title="Atomic save", what="Must not persist"), project="test-project")

    assert container.memory_repo.count() == 0
    assert not list(Path(container.vault_dir).rglob("*-session.md"))


def test_memory_update_rolls_back_when_vector_storage_fails(container, monkeypatch):
    service = MemoryService(container)
    memory = service.save(RawMemoryInput(title="Atomic update", what="Original"), project="test-project")

    def fail_vector_store(*_args, **_kwargs):
        raise RuntimeError("vector store failed")

    monkeypatch.setattr(container.memory_repo, "insert_vector", fail_vector_store)

    with pytest.raises(RuntimeError, match="vector store failed"):
        service.update(memory["id"], what="Should roll back")

    assert container.memory_repo.get(memory["id"])["what"] == "Original"


def test_concurrent_processes_preserve_every_memory_and_markdown_section(tmp_path):
    home = str(tmp_path / "arcane-home")
    with create_container(home):
        pass

    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [context.Process(target=_save_memory_worker, args=(home, index, start, results)) for index in range(8)]

    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=30)

    assert [worker.exitcode for worker in workers] == [0] * len(workers)
    assert [results.get(timeout=5) for _ in workers] == [None] * len(workers)

    with create_container(home) as container:
        assert container.memory_repo.count() == len(workers)

    session_files = list(Path(home, "vault", "shared-project").glob("*-session.md"))
    assert len(session_files) == 1
    content = session_files[0].read_text()
    for index in range(len(workers)):
        assert f"Concurrent memory {index}" in content
