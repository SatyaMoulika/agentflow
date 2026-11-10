"""Logging configuration, safe field selection, and level filtering."""

import json
import logging

import pytest

from app.core.logging import HANDLER_NAME, JsonFormatter, configure_logging, request_id_context


def test_formatter_omits_arbitrary_extras_and_exception_text() -> None:
    try:
        raise RuntimeError("secret-exception-value")
    except RuntimeError as exc:
        record = logging.LogRecord(
            "agentflow.test",
            logging.ERROR,
            __file__,
            1,
            "Operation failed",
            (),
            (type(exc), exc, exc.__traceback__),
        )
    record.credential = "secret-extra-value"
    record.route = "/test/{id}"
    token = request_id_context.set("req_" + "a" * 32)
    try:
        output = JsonFormatter().format(record)
    finally:
        request_id_context.reset(token)

    payload = json.loads(output)
    assert payload["request_id"] == "req_" + "a" * 32
    assert payload["route"] == "/test/{id}"
    assert payload["timestamp"].endswith("+00:00")
    assert "secret-" not in output
    assert "exc_info" not in payload


def test_configuration_is_idempotent_filters_levels_and_leaves_root_untouched(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    previous_root = (root.handlers[:], root.level)
    configure_logging("INFO")
    configure_logging("WARNING")
    logger = logging.getLogger("agentflow")
    assert len([handler for handler in logger.handlers if handler.name == HANDLER_NAME]) == 1
    logger.info("Hidden info")
    logger.error("Visible error")

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record["message"] for record in records] == ["Visible error"]
    assert records[0]["request_id"] is None
    assert (root.handlers, root.level) == previous_root
