"""Run the separate JSON-only transport and pure workflow worker."""

import sys

from app.core.config import ConfigurationError, load_settings
from app.core.logging import configure_logging
from app.infrastructure.database.session import Database
from app.workers.celery_app import WorkerConfigurationError, create_celery


def main(*, workflow_database: Database | None = None) -> int:
    try:
        settings = load_settings()
        app = create_celery(settings, workflow_database=workflow_database)
    except (ConfigurationError, WorkerConfigurationError) as error:
        print(str(error), file=sys.stderr)
        return 2
    configure_logging(settings.log_level)
    try:
        # Celery's CLI wrapper does not reliably return the worker's exit code
        # to its Python caller. Read it from the controller for supervisors.
        worker = app.Worker(
            pool="solo",
            concurrency=1,
            loglevel="INFO",
            without_gossip=True,
            without_mingle=True,
            without_heartbeat=True,
        )
        worker.start()
        code = worker.exitcode
    finally:
        app.close()
    return code if isinstance(code, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
