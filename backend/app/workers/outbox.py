"""Dispatch retained workflow/probe intents and periodically rediscover lost work."""

import argparse
import signal
import sys
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import ConfigurationError, load_settings
from app.core.tracing import configure_local_export, shutdown_export
from app.infrastructure.database.session import Database
from app.modules.approvals.service import ApprovalService
from app.modules.executions.dispatch import schedule_recovery
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.outbox.repository import OutboxRepository
from app.workers.celery_app import (
    WorkerConfigurationError,
    create_celery,
    publish_outbox_probe,
    publish_workflow,
)


def main(*, workflow_database: Database | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["enqueue-probe", "dispatch-once", "run"])
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if not 0.1 <= args.interval <= 30:
        parser.error("interval must be between 0.1 and 30 seconds")
    try:
        settings = load_settings()
        configure_local_export(settings.trace_export_enabled)
        if settings.database_url is None and workflow_database is None:
            print("Set AGENTFLOW_DATABASE_URL before using the outbox.", file=sys.stderr)
            return 2
        if workflow_database is None:
            assert settings.database_url is not None
            database = Database(settings.database_url)
        else:
            database = workflow_database
        try:
            if args.command == "enqueue-probe":
                with database.unit_of_work() as session:
                    message_id = OutboxRepository(session).enqueue_probe()
                print(f"Outbox probe queued: {message_id}")
                return 0
            app = create_celery(settings)
            try:
                dispatcher = OutboxDispatcher(
                    database,
                    lambda message_id: publish_outbox_probe(app, settings.worker_queue, message_id),
                    publish_workflow=lambda message_id: publish_workflow(
                        app, settings.worker_queue, message_id
                    ),
                )
                stopped = Event()
                previous = {}
                if args.command == "run":
                    for signum in (signal.SIGINT, signal.SIGTERM):
                        previous[signum] = signal.signal(signum, lambda *_: stopped.set())
                try:
                    while True:
                        try:
                            ApprovalService(database).expire_due()
                            scheduled = schedule_recovery(
                                database, redelivery_seconds=settings.worker_redelivery_seconds
                            )
                            result = dispatcher.dispatch_once()
                            print(
                                f"Outbox: scheduled={scheduled} claimed={result.claimed} "
                                f"published={result.published} failed={result.failed} "
                                f"stale={result.stale}",
                                flush=True,
                            )
                            if args.command == "dispatch-once":
                                return 1 if result.failed or result.stale else 0
                        except SQLAlchemyError:
                            if args.command != "run":
                                raise
                            print(
                                "Outbox storage is unavailable; intents retained.", file=sys.stderr
                            )
                        if stopped.wait(args.interval):
                            return 0
                finally:
                    for signum, handler in previous.items():
                        signal.signal(signum, handler)
            finally:
                app.close()
        finally:
            if workflow_database is None:
                database.dispose()
    except (ConfigurationError, WorkerConfigurationError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("Outbox storage is unavailable.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutdown_export()
