"""Maintained PostgreSQL saver in a separate schema; runtime never performs setup DDL."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import sql
from psycopg.rows import dict_row

from app.infrastructure.database.session import Database
from app.modules.executions.exceptions import ExecutionStorageUnavailableError


def checkpoint_schema(database: Database) -> str:
    # Disposable integration engines translate the application schema. Never let their
    # checkpoint setup touch the development/default checkpoint schema.
    mapping = database.engine.get_execution_options().get("schema_translate_map") or {}
    application_schema = mapping.get(None, "public")
    schema = (
        "agentflow_checkpoints"
        if application_schema == "public"
        else f"{application_schema}_agents"
    )
    if not isinstance(schema, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsupported checkpoint schema")
    return schema


@contextmanager
def checkpoint_saver(database: Database) -> Iterator[PostgresSaver]:
    parameters: dict[str, Any] = dict(database.engine.url.query)
    parameters.update(
        database.engine.url.translate_connect_args(database="dbname", username="user")
    )
    connection_options = parameters.pop("options", "")
    try:
        with psycopg.Connection[dict[str, Any]].connect(
            **parameters,
            autocommit=True,
            prepare_threshold=0,
            connect_timeout=5,
            options=f"{connection_options} -csearch_path={checkpoint_schema(database)}".strip(),
            row_factory=dict_row,
        ) as connection:
            # Only primitive graph state is expected; never enable object/pickle loading.
            yield PostgresSaver(
                connection,
                serde=JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=[]),
            )
    except psycopg.Error:
        raise ExecutionStorageUnavailableError() from None


def setup_checkpoints(database: Database) -> None:
    """Explicit operator command; saver setup owns its migrations, separately from Alembic."""
    with checkpoint_saver(database) as saver:
        assert isinstance(saver.conn, psycopg.Connection)
        connection = saver.conn
        # Serialize concurrent setup processes without holding a transaction across the
        # adapter's concurrent-index migrations (which require autocommit).
        connection.execute("SELECT pg_advisory_lock(hashtext('agentflow-checkpoint-setup'))")
        try:
            connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(checkpoint_schema(database))
                )
            )
            saver.setup()
        finally:
            connection.execute("SELECT pg_advisory_unlock(hashtext('agentflow-checkpoint-setup'))")
