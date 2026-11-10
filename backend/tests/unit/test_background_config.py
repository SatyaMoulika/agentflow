"""Background mode is explicit, bounded and does not require contacting any service."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.workers.celery_app import WORKFLOW_TASK, create_celery, publish_workflow


def test_background_execution_defaults_off() -> None:
    settings = Settings()
    assert settings.background_execution_enabled is False
    assert settings.worker_lease_seconds == settings.worker_redelivery_seconds == 30


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"database_url": SecretStr("postgresql+psycopg://localhost/agentflow_test")},
        {"redis_url": SecretStr("redis://localhost/15")},
    ],
)
def test_background_mode_requires_explicit_storage_and_broker_configuration(extra) -> None:
    with pytest.raises(ValidationError, match="background execution requires"):
        Settings(background_execution_enabled=True, **extra)


@pytest.mark.parametrize("field", ["worker_lease_seconds", "worker_redelivery_seconds"])
@pytest.mark.parametrize("value", [4, 3601])
def test_worker_timing_is_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


def test_workflow_publication_sends_only_the_retained_delivery_uuid() -> None:
    settings = Settings(redis_url=SecretStr("redis://127.0.0.1:16380/15"))
    app = create_celery(settings)
    identifier = uuid4()
    try:
        with patch.object(app, "send_task") as send:
            publish_workflow(app, settings.worker_queue, identifier)
        send.assert_called_once_with(
            WORKFLOW_TASK,
            args=(str(identifier),),
            kwargs={},
            task_id=str(identifier),
            queue=settings.worker_queue,
            retry=False,
        )
    finally:
        app.close()
