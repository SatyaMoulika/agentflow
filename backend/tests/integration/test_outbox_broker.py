"""End-to-end outbox → isolated Redis → real Celery worker."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import select

from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.outbox.models import OutboxMessage
from app.modules.outbox.repository import OutboxRepository
from app.workers.celery_app import create_celery, publish_outbox_probe

pytestmark = [pytest.mark.integration, pytest.mark.redis_integration]


def test_database_commit_dispatches_payload_free_probe_to_real_worker(
    repository_database: Database, tmp_path: Path
) -> None:
    url = os.environ.get("TEST_REDIS_URL", "")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "redis"
            and parsed.hostname in {"localhost", "127.0.0.1"}
            and parsed.port == 16380
            and parsed.path == "/15"
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        valid = False
    if not valid:
        pytest.fail(
            "TEST_REDIS_URL must reference the local disposable Redis test service", pytrace=False
        )
    queue = f"agentflow.test.{uuid4().hex}"
    app = create_celery(Settings(redis_url=SecretStr(url), worker_queue=queue))
    env = {
        k: v for k, v in os.environ.items() if not k.upper().startswith(("AGENTFLOW_", "CELERY_"))
    }
    env.update(
        AGENTFLOW_REDIS_URL=url,
        AGENTFLOW_WORKER_QUEUE=queue,
        AGENTFLOW_ENVIRONMENT="testing",
        PYTHONUNBUFFERED="1",
    )
    bootstrap = (
        'from app.core.config import Settings; Settings.model_config["env_file"] = None; '
        "from app.workers.__main__ import main; raise SystemExit(main())"
    )
    log_path = tmp_path / "outbox-worker.log"
    with repository_database.unit_of_work() as session:
        message_id = OutboxRepository(session).enqueue_probe()
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", bootstrap], env=env, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            for _ in range(150):
                assert process.poll() is None
                if " ready." in log_path.read_text():
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Worker did not become ready")
            result = OutboxDispatcher(
                repository_database, lambda value: publish_outbox_probe(app, queue, value)
            ).dispatch_once()
            assert (result.claimed, result.published, result.failed, result.stale) == (1, 1, 0, 0)
            for _ in range(150):
                entries = []
                for line in log_path.read_text().splitlines():
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if record.get("message") == "Outbox probe consumed":
                        entries.append(record)
                if entries:
                    break
                assert process.poll() is None
                time.sleep(0.1)
            else:
                pytest.fail("Outbox probe was not consumed")
            assert len(entries) == 1 and entries[0]["probe_id"] == str(message_id)
            with repository_database.session() as session:
                row = session.scalar(select(OutboxMessage).where(OutboxMessage.id == message_id))
                assert row is not None and row.published_at is not None and row.attempts == 1
            assert (
                OutboxDispatcher(repository_database, lambda _: pytest.fail("Unexpected duplicate"))
                .dispatch_once()
                .claimed
                == 0
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                pytest.fail("Worker did not stop")
            app.close()
            redis = Redis.from_url(url)
            redis.delete(
                queue,
                *(queue + "\x06\x16" + str(priority) for priority in (3, 6, 9)),
                f"_kombu.binding.{queue}",
            )
            redis.close()
    assert process.returncode in (0, -15)
