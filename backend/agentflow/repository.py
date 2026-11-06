"""SQLite repository with serialized transactions and durable JSON domain snapshots."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

TABLES = {'workflows', 'executions', 'approvals', 'integrations', 'settings'}


class Repository:
    def __init__(self, path: str):
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA busy_timeout=5000')
        self.lock = RLock()
        with self.transaction():
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES(1);
                CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS executions(
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL REFERENCES workflows(id),
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS executions_workflow ON executions(workflow_id);
                CREATE TABLE IF NOT EXISTS approvals(
                    id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL REFERENCES executions(id),
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS approvals_execution ON approvals(execution_id);
                CREATE TABLE IF NOT EXISTS integrations(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idempotency(
                    key TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL REFERENCES executions(id),
                    request_hash TEXT NOT NULL
                );
            ''')

    @contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                yield self
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.rollback()
                raise
            else:
                if self.connection.in_transaction:
                    self.connection.commit()

    def get(self, table: str, identifier: str) -> dict[str, Any] | None:
        if table not in TABLES:
            raise ValueError('Unknown repository table')
        with self.lock:
            row = self.connection.execute(
                f'SELECT payload FROM {table} WHERE id=?', (identifier,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, table: str) -> list[dict[str, Any]]:
        if table not in TABLES:
            raise ValueError('Unknown repository table')
        with self.lock:
            rows = self.connection.execute(f'SELECT payload FROM {table} ORDER BY rowid DESC').fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, table: str, data: dict[str, Any]) -> None:
        if table not in TABLES:
            raise ValueError('Unknown repository table')
        extra = {'executions': ('workflow_id', 'workflowId'), 'approvals': ('execution_id', 'executionId')}
        with self.lock:
            if table in extra:
                column, key = extra[table]
                self.connection.execute(
                    f'INSERT INTO {table}(id,{column},payload) VALUES(?,?,?) '
                    f'ON CONFLICT(id) DO UPDATE SET {column}=excluded.{column},payload=excluded.payload',
                    (data['id'], data[key], json.dumps(data, allow_nan=False)),
                )
            else:
                self.connection.execute(
                    f'INSERT INTO {table}(id,payload) VALUES(?,?) '
                    'ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                    (data['id'], json.dumps(data, allow_nan=False)),
                )

    def close(self):
        with self.lock:
            self.connection.close()
