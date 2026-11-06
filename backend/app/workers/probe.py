"""Publish a payload-free transport probe; no workflow or database is touched."""

import sys

from app.core.config import ConfigurationError, load_settings
from app.workers.celery_app import (
    TransportUnavailableError,
    WorkerConfigurationError,
    create_celery,
    publish_probe,
)


def main() -> int:
    try:
        settings = load_settings()
        app = create_celery(settings)
        try:
            probe_id = publish_probe(app, settings.worker_queue)
        finally:
            app.close()
    except (ConfigurationError, WorkerConfigurationError, TransportUnavailableError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"Probe submitted: {probe_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
