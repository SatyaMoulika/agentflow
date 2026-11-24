"""Mapper configuration and offline migration rendering need no database."""

from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import configure_mappers

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import User, Workflow, WorkflowVersion


def test_all_relationships_configure_without_ambiguous_foreign_keys() -> None:
    configure_mappers()

    assert set(Base.metadata.tables) == {
        "users",
        "workflows",
        "workflow_versions",
        "refresh_sessions",
        "refresh_tokens",
        "workflow_runs",
        "node_runs",
        "execution_events",
        "run_commands",
        "outbox_messages",
        "run_claims",
        "workflow_dispatches",
        "node_retries",
        "connections",
        "agent_invocations",
        "gmail_authorizations",
        "gmail_connections",
        "approvals",
    }
    assert User.workflows.property.back_populates == "owner"
    assert Workflow.versions.property.back_populates == "workflow"
    assert Workflow.current_version.property.viewonly is True
    assert WorkflowVersion.creator.property.back_populates == "created_versions"


def test_offline_upgrade_renders_in_dependency_order_without_database_url() -> None:
    output = StringIO()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"), output_buffer=output)

    command.upgrade(config, "head", sql=True)

    ddl = output.getvalue()
    assert ddl.index("CREATE TABLE users") < ddl.index("CREATE TABLE workflows")
    assert ddl.index("CREATE TABLE workflows") < ddl.index("CREATE TABLE workflow_versions")
    assert ddl.index("CREATE TABLE workflow_versions") < ddl.index(
        "ADD CONSTRAINT fk_workflows_current_version"
    )
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE" in ddl
    assert "postgresql+psycopg" not in ddl
