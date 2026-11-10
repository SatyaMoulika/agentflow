"""Retain explicit provider failure outcomes without changing business payloads.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None

OLD_CODES = (
    "EXECUTION_FAILED",
    "INPUT_MAPPING_FAILED",
    "DEADLINE_EXCEEDED",
    "INTERNAL_FAILURE",
    "CONNECTION_UNAVAILABLE",
    "HTTP_REQUEST_FAILED",
    "HTTP_TARGET_BLOCKED",
)
NEW_CODES = (
    "PROVIDER_NOT_CONFIGURED",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_MODEL_UNAVAILABLE",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_CONTEXT_LIMIT",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_INVALID_RESPONSE",
    "PROVIDER_OUTPUT_LIMIT",
)


def _constraints(codes: tuple[str, ...]) -> None:
    values = ", ".join(f"'{code}'" for code in codes)
    for table in ("workflow_runs", "node_runs"):
        name = op.f(f"ck_{table}_failure_code")
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"error_code IN ({values})")


def upgrade() -> None:
    _constraints(OLD_CODES + NEW_CODES)


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in NEW_CODES)
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM workflow_runs WHERE error_code IN ({codes})) OR
             EXISTS (SELECT 1 FROM node_runs WHERE error_code IN ({codes})) THEN
            RAISE EXCEPTION 'Provider failure history must be retained' USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    _constraints(OLD_CODES)
