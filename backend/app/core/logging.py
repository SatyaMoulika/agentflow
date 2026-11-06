"""Application JSON logging with request-local correlation and explicit fields."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
HANDLER_NAME = "agentflow-json"


class JsonFormatter(logging.Formatter):
    """Serialize known operational fields; omit exception text and arbitrary extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for field in (
            "environment",
            "method",
            "route",
            "status_code",
            "duration_ms",
            "error_type",
            "probe_id",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, ensure_ascii=True, allow_nan=False)


def configure_logging(level: str) -> None:
    """Configure only AgentFlow at startup; repeated startup does not duplicate output."""
    logger = logging.getLogger("agentflow")
    if not any(handler.name == HANDLER_NAME for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(HANDLER_NAME)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
