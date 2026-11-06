"""Explicit Redis/Celery transport configuration for a harmless probe task."""

import logging
import os
import ssl
from uuid import UUID, uuid4

from celery import Celery
from kombu.entity import Queue
from kombu.exceptions import OperationalError
from redis.exceptions import RedisError

from app.core.config import Settings
from app.infrastructure.database.session import Database

PROBE_TASK = "agentflow.transport.probe"
OUTBOX_PROBE_TASK = "agentflow.transport.outbox_probe"
WORKFLOW_TASK = "agentflow.workflow.execute"
CELERY_OVERRIDES = (
    "CELERY_BROKER_URL",
    "CELERY_BROKER_READ_URL",
    "CELERY_BROKER_WRITE_URL",
    "CELERY_RESULT_BACKEND",
    "CELERY_CONFIG_MODULE",
    "CELERY_LOADER",
)
logger = logging.getLogger("agentflow.worker.probe")


class WorkerConfigurationError(RuntimeError):
    """Missing worker configuration; never include the broker URL."""


class TransportUnavailableError(RuntimeError):
    """A bounded probe could not be published; never include driver errors."""


def create_celery(settings: Settings, *, workflow_database: Database | None = None) -> Celery:
    """Create a separate app without network access or a default localhost broker."""
    if settings.redis_url is None:
        raise WorkerConfigurationError("Set AGENTFLOW_REDIS_URL before starting the worker.")
    if any(os.environ.get(name) for name in CELERY_OVERRIDES):
        raise WorkerConfigurationError(
            "Conflicting Celery environment overrides are set; use AgentFlow worker settings."
        )
    url = settings.redis_url.get_secret_value()
    app = Celery(
        "agentflow",
        broker=url,
        backend=None,
        loader="celery.loaders.app:AppLoader",
        set_as_current=False,
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_store_errors_even_if_ignored=False,
        task_publish_retry=False,
        task_acks_late=False,
        worker_prefetch_multiplier=1,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_send_sent_event=False,
        worker_hijack_root_logger=False,
        worker_redirect_stdouts=False,
        broker_connection_retry_on_startup=False,
        broker_connection_timeout=3,
        broker_transport_options={"socket_timeout": 3, "socket_connect_timeout": 3},
        task_default_queue=settings.worker_queue,
        task_default_exchange=settings.worker_queue,
        task_default_routing_key=settings.worker_queue,
        task_queues=(Queue(settings.worker_queue),),
        task_create_missing_queues=False,
        broker_use_ssl={"ssl_cert_reqs": ssl.CERT_REQUIRED}
        if url.startswith("rediss://")
        else None,
    )

    @app.task(bind=True, name=PROBE_TASK, ignore_result=True, shared=False)
    def probe(task: object) -> None:
        # The task has no user-provided arguments or business payload. Its ID is
        # only a random correlation value; malformed IDs are never logged.
        request = getattr(task, "request", None)
        value = getattr(request, "id", None)
        try:
            valid = isinstance(value, str) and str(UUID(value)) == value
        except ValueError:
            valid = False
        if valid:
            logger.info("Transport probe consumed", extra={"probe_id": value})
        else:
            logger.warning("Transport probe had an invalid identifier")

    @app.task(bind=True, name=OUTBOX_PROBE_TASK, ignore_result=True, shared=False)
    def outbox_probe(task: object, outbox_id: str) -> None:
        try:
            valid = isinstance(outbox_id, str) and str(UUID(outbox_id)) == outbox_id
        except ValueError:
            valid = False
        if valid:
            logger.info("Outbox probe consumed", extra={"probe_id": outbox_id})
        else:
            logger.warning("Outbox probe had an invalid identifier")

    @app.task(name=WORKFLOW_TASK, ignore_result=True, shared=False)
    def workflow(outbox_id: str) -> None:
        from app.workers.workflow_tasks import consume_workflow

        if workflow_database is None and settings.database_url is None:
            logger.warning("Workflow delivery requires database configuration")
            return
        database = workflow_database
        try:
            if database is None:
                assert settings.database_url is not None
                database = Database(settings.database_url)
            consume_workflow(database, outbox_id, lease_seconds=settings.worker_lease_seconds)
        except Exception:
            logger.warning("Workflow delivery storage is unavailable")
        finally:
            if database is not None and workflow_database is None:
                try:
                    database.dispose()
                except Exception:
                    logger.warning("Workflow delivery storage cleanup failed")

    return app


def publish_outbox_probe(app: Celery, queue: str, message_id: UUID) -> None:
    """Publish only the fixed task name and opaque message ID; no user payload."""
    try:
        app.send_task(
            OUTBOX_PROBE_TASK,
            args=(str(message_id),),
            kwargs={},
            task_id=str(message_id),
            queue=queue,
            retry=False,
        )
    except (OperationalError, RedisError, OSError, TimeoutError):
        raise TransportUnavailableError("The worker transport is unavailable.") from None


def publish_workflow(app: Celery, queue: str, message_id: UUID) -> None:
    """Only the retained outbox UUID crosses Redis; no owner, graph, input or secret."""
    try:
        app.send_task(
            WORKFLOW_TASK,
            args=(str(message_id),),
            kwargs={},
            task_id=str(message_id),
            queue=queue,
            retry=False,
        )
    except (OperationalError, RedisError, OSError, TimeoutError):
        raise TransportUnavailableError("The worker transport is unavailable.") from None


def publish_probe(app: Celery, queue: str) -> UUID:
    """Publish one data-free probe without hidden retries or a result backend."""
    probe_id = uuid4()
    try:
        app.send_task(
            PROBE_TASK, args=(), kwargs={}, task_id=str(probe_id), queue=queue, retry=False
        )
    except (OperationalError, RedisError, OSError, TimeoutError):
        raise TransportUnavailableError("The worker transport is unavailable.") from None
    return probe_id
