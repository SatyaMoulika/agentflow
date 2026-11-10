"""Outbox transactional, concurrency and recovery behavior on real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.infrastructure.database.session import Database
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.outbox.models import OutboxMessage
from app.modules.outbox.repository import OutboxRepository

pytestmark = pytest.mark.integration


def enqueue(database: Database, count: int = 1):
    with database.unit_of_work() as session:
        return [OutboxRepository(session).enqueue_probe() for _ in range(count)]


def test_enqueue_rolls_back_with_caller_transaction(repository_database: Database) -> None:
    with pytest.raises(RuntimeError), repository_database.unit_of_work() as session:
        OutboxRepository(session).enqueue_probe()
        raise RuntimeError("rollback")
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_success_and_broker_outage_preserve_intents(repository_database: Database) -> None:
    ids = enqueue(repository_database, 2)
    sent = []

    def publish(message_id):
        sent.append(message_id)
        if message_id == ids[0]:
            raise OSError("private broker detail")

    result = OutboxDispatcher(repository_database, publish).dispatch_once()
    assert (result.claimed, result.published, result.failed, result.stale) == (2, 1, 1, 0)
    with repository_database.session() as session:
        failed, successful = [session.get(OutboxMessage, item) for item in ids]
        assert failed is not None and failed.published_at is None and failed.lease_token is None
        assert successful is not None and successful.published_at is not None
    retried = OutboxDispatcher(repository_database, sent.append).dispatch_once()
    assert (retried.claimed, retried.published) == (1, 1)
    assert sent.count(ids[0]) == 2 and sent.count(ids[1]) == 1


def test_expired_lease_fences_stale_writer_and_republishes(repository_database: Database) -> None:
    message_id = enqueue(repository_database)[0]
    with repository_database.unit_of_work() as session:
        old = OutboxRepository(session).claim()[0]
    with repository_database.unit_of_work() as session:
        row = session.get(OutboxMessage, message_id)
        assert row is not None and row.lease_until is not None
        row.lease_until -= timedelta(minutes=1)
    with repository_database.unit_of_work() as session:
        current = OutboxRepository(session).claim()[0]
        assert old.id == current.id and old.lease_token != current.lease_token
        assert not OutboxRepository(session).mark_published(old)
        assert not OutboxRepository(session).release(old)
        assert OutboxRepository(session).mark_published(current)
    with repository_database.session() as session:
        row = session.get(OutboxMessage, message_id)
        assert row is not None and row.attempts == 2 and row.published_at is not None


def test_parallel_claimers_never_claim_the_same_row(repository_database: Database) -> None:
    expected = set(enqueue(repository_database, 8))
    gate = Barrier(2)

    def worker():
        with repository_database.unit_of_work() as session:
            gate.wait(timeout=5)
            return OutboxRepository(session).claim(limit=8)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(worker), pool.submit(worker)
        first, second = a.result(10), b.result(10)
    ids1, ids2 = {row.id for row in first}, {row.id for row in second}
    assert not ids1 & ids2
    assert ids1 | ids2 == expected


def test_publish_accepted_but_mark_failed_leaves_intent_recoverable(
    repository_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    message_id = enqueue(repository_database)[0]
    sent = []
    original = OutboxRepository.mark_published

    def crash(self, claim):
        raise RuntimeError("process died after publish")

    monkeypatch.setattr(OutboxRepository, "mark_published", crash)
    with pytest.raises(RuntimeError):
        OutboxDispatcher(repository_database, sent.append).dispatch_once()
    with repository_database.unit_of_work() as session:
        row = session.get(OutboxMessage, message_id)
        assert row is not None and row.published_at is None and row.lease_until is not None
        row.lease_until -= timedelta(minutes=1)
    monkeypatch.setattr(OutboxRepository, "mark_published", original)
    result = OutboxDispatcher(repository_database, sent.append).dispatch_once()
    assert result.published == 1 and sent == [message_id, message_id]


@pytest.mark.parametrize(("limit", "lease"), [(0, 30), (101, 30), (True, 30), (1, 4), (1, 3601)])
def test_claim_bounds(repository_database: Database, limit: int, lease: int) -> None:
    with repository_database.session() as session, pytest.raises(ValueError):
        OutboxRepository(session).claim(limit=limit, lease_seconds=lease)
