"""No-network worker configuration, safe failures and bounded probe contract."""

import logging
import ssl
from unittest.mock import patch

import pytest
from kombu.exceptions import OperationalError
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.workers.celery_app import (
    OUTBOX_PROBE_TASK,
    PROBE_TASK,
    WORKFLOW_TASK,
    TransportUnavailableError,
    WorkerConfigurationError,
    create_celery,
    publish_probe,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/0",
        "redis:///0",
        "redis://localhost",
        "redis://localhost/16",
        "redis://localhost/-1",
        "redis://localhost/0?private=secret",
        "redis://localhost/0#secret",
        "redis://localhost:99999/0",
        "redis://localhost/0\n",
        "redis://host name/0",
        "redis://localhost/a",
    ],
)
def test_invalid_redis_url_is_rejected_without_echoing_input(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(redis_url=SecretStr(url))
    assert url not in str(error.value)


@pytest.mark.parametrize(
    "queue", ["other.queue", "agentflow.", "agentflow.bad space", "agentflow.é"]
)
def test_invalid_queue_is_rejected(queue: str) -> None:
    with pytest.raises(ValidationError):
        Settings(worker_queue=queue)


def test_default_api_configuration_does_not_require_redis() -> None:
    settings = Settings()
    assert settings.redis_url is None
    with pytest.raises(WorkerConfigurationError, match="AGENTFLOW_REDIS_URL"):
        create_celery(settings)


@pytest.mark.parametrize(
    "name",
    [
        "CELERY_BROKER_URL",
        "CELERY_BROKER_READ_URL",
        "CELERY_BROKER_WRITE_URL",
        "CELERY_RESULT_BACKEND",
        "CELERY_CONFIG_MODULE",
        "CELERY_LOADER",
    ],
)
def test_unvalidated_celery_environment_overrides_are_refused(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, "private-override-value")
    with pytest.raises(WorkerConfigurationError) as failure:
        create_celery(Settings(redis_url=SecretStr("redis://127.0.0.1:16380/15")))
    assert "private-override-value" not in str(failure.value)


def test_production_requires_tls_and_password_only_when_redis_is_configured() -> None:
    assert Settings(environment="production").redis_url is None
    for url in ("redis://:private@host/0", "rediss://host/0"):
        with pytest.raises(ValidationError) as error:
            Settings(environment="production", redis_url=SecretStr(url))
        assert "private" not in str(error.value)
    settings = Settings(environment="production", redis_url=SecretStr("rediss://:private@host/0"))
    app = create_celery(settings)
    try:
        assert app.conf.broker_use_ssl == {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    finally:
        app.close()


def test_worker_app_uses_json_only_and_no_result_backend() -> None:
    app = create_celery(Settings(redis_url=SecretStr("redis://127.0.0.1:16380/15")))
    try:
        assert app.conf.accept_content == ["json"]
        assert app.conf.task_serializer == "json"
        assert app.conf.task_ignore_result is True
        assert app.conf.task_publish_retry is False
        assert app.conf.task_acks_late is False
        assert app.conf.worker_enable_remote_control is False
        assert PROBE_TASK in app.tasks
        assert OUTBOX_PROBE_TASK in app.tasks
        assert WORKFLOW_TASK in app.tasks
        assert not any(
            name.startswith("agentflow.")
            and name not in {PROBE_TASK, OUTBOX_PROBE_TASK, WORKFLOW_TASK}
            for name in app.tasks
        )
    finally:
        app.close()


def test_failed_publish_is_static_and_not_retried() -> None:
    settings = Settings(redis_url=SecretStr("redis://:private-password@127.0.0.1:16380/15"))
    app = create_celery(settings)
    try:
        with patch.object(
            app, "send_task", side_effect=OperationalError("private-driver-password")
        ) as send:
            with pytest.raises(TransportUnavailableError) as failure:
                publish_probe(app, settings.worker_queue)
            assert "private" not in str(failure.value)
            assert send.call_count == 1
    finally:
        app.close()


def test_probe_with_malformed_task_identifier_logs_no_supplied_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_celery(Settings(redis_url=SecretStr("redis://127.0.0.1:16380/15")))
    try:
        with caplog.at_level(logging.INFO, logger="agentflow"):
            result = app.tasks[PROBE_TASK].apply(task_id="private-malformed-id")
        assert result.successful()
        assert "private-malformed-id" not in caplog.text
        assert "invalid identifier" in caplog.text
    finally:
        app.close()
