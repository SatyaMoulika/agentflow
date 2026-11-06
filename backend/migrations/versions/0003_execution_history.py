"""Durable runs, node attempts and ordered events.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "trigger_type", sa.String(length=16), server_default=sa.text("'manual'"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "waiting_approval",
                "succeeded",
                "failed",
                "cancelled",
                name="run_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("revision", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("event_sequence", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "input_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_json", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "error_code",
            sa.Enum(
                "EXECUTION_FAILED",
                "INPUT_MAPPING_FAILED",
                "DEADLINE_EXCEEDED",
                "INTERNAL_FAILURE",
                name="failure_code",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name=op.f("ck_workflow_runs_failure_code_required"),
        ),
        sa.CheckConstraint(
            (
                "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL) OR "
                "(status IN ('running', 'waiting_approval') AND started_at IS NOT NULL "
                "AND completed_at IS NULL) OR (status IN ('succeeded', 'failed', "
                "'cancelled') AND completed_at IS NOT NULL AND (status <> 'succeeded' OR "
                "started_at IS NOT NULL))"
            ),
            name=op.f("ck_workflow_runs_lifecycle_timestamps"),
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (output_json IS NOT NULL)",
            name=op.f("ck_workflow_runs_success_output"),
        ),
        sa.CheckConstraint(
            ("jsonb_typeof(input_json) = 'object' AND octet_length(input_json::text) <= 1048576"),
            name=op.f("ck_workflow_runs_input_object"),
        ),
        sa.CheckConstraint(
            (
                "output_json IS NULL OR (jsonb_typeof(output_json) = 'object' AND "
                "octet_length(output_json::text) <= 1048576)"
            ),
            name=op.f("ck_workflow_runs_output_object"),
        ),
        sa.CheckConstraint("trigger_type = 'manual'", name=op.f("ck_workflow_runs_manual_trigger")),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= coalesce(started_at, created_at)",
            name=op.f("ck_workflow_runs_completion_after_start"),
        ),
        sa.CheckConstraint(
            "parent_run_id IS NULL OR parent_run_id <> id",
            name=op.f("ck_workflow_runs_parent_not_self"),
        ),
        sa.CheckConstraint(
            "revision >= 0 AND event_sequence >= 0",
            name=op.f("ck_workflow_runs_nonnegative_counters"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name=op.f("ck_workflow_runs_start_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "workflow_version_id", "parent_run_id"],
            ["workflow_runs.workflow_id", "workflow_runs.workflow_version_id", "workflow_runs.id"],
            name="fk_workflow_runs_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "workflow_version_id"],
            ["workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_workflow_runs_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_workflow_runs_workflow_id_workflows"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_runs")),
        sa.UniqueConstraint(
            "workflow_id", "workflow_version_id", "id", name="uq_workflow_runs_workflow_version_id"
        ),
    )
    op.create_index(
        "ix_workflow_runs_parent_run_id", "workflow_runs", ["parent_run_id"], unique=False
    )
    op.create_index(
        "ix_workflow_runs_status_created_id",
        "workflow_runs",
        ["status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_runs_workflow_created_id",
        "workflow_runs",
        ["workflow_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "node_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "waiting_approval",
                "succeeded",
                "failed",
                "skipped",
                "cancelled",
                name="node_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("revision", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "input_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_json", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "error_code",
            sa.Enum(
                "EXECUTION_FAILED",
                "INPUT_MAPPING_FAILED",
                "DEADLINE_EXCEEDED",
                "INTERNAL_FAILURE",
                name="failure_code",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name=op.f("ck_node_runs_failure_code_required"),
        ),
        sa.CheckConstraint(
            (
                "(status = 'pending' AND started_at IS NULL AND completed_at IS NULL AND "
                "duration_ms IS NULL) OR (status IN ('running', 'waiting_approval') AND "
                "started_at IS NOT NULL AND completed_at IS NULL AND duration_ms IS NULL)"
                " OR (status IN ('succeeded', 'failed', 'skipped', 'cancelled') AND "
                "completed_at IS NOT NULL AND duration_ms IS NOT NULL AND (status <> "
                "'succeeded' OR started_at IS NOT NULL) AND (status <> 'skipped' OR "
                "started_at IS NULL))"
            ),
            name=op.f("ck_node_runs_lifecycle_timestamps"),
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (output_json IS NOT NULL)",
            name=op.f("ck_node_runs_success_output"),
        ),
        sa.CheckConstraint(
            ("jsonb_typeof(input_json) = 'object' AND octet_length(input_json::text) <= 1048576"),
            name=op.f("ck_node_runs_input_object"),
        ),
        sa.CheckConstraint(
            "node_id ~ '^[A-Za-z_][A-Za-z0-9_-]{0,63}$'", name=op.f("ck_node_runs_node_id_format")
        ),
        sa.CheckConstraint(
            (
                "output_json IS NULL OR (jsonb_typeof(output_json) = 'object' AND "
                "octet_length(output_json::text) <= 1048576)"
            ),
            name=op.f("ck_node_runs_output_object"),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1 AND revision >= 0",
            name=op.f("ck_node_runs_positive_attempt_revision"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= coalesce(started_at, created_at)",
            name=op.f("ck_node_runs_completion_after_start"),
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name=op.f("ck_node_runs_duration_nonnegative"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name=op.f("ck_node_runs_start_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_node_runs_workflow_run_id_workflow_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_node_runs")),
        sa.UniqueConstraint("workflow_run_id", "id", name="uq_node_runs_run_id"),
        sa.UniqueConstraint(
            "workflow_run_id", "node_id", "attempt_number", name="uq_node_runs_run_node_attempt"
        ),
    )
    op.create_index(
        "ix_node_runs_one_open_attempt",
        "node_runs",
        ["workflow_run_id", "node_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'waiting_approval')"),
    )
    op.create_index(
        "ix_node_runs_run_created_id",
        "node_runs",
        ["workflow_run_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "execution_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("node_run_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "run.created",
                "run.status_changed",
                "node.created",
                "node.status_changed",
                name="event_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            (
                "jsonb_typeof(event_payload) = 'object' AND "
                "octet_length(event_payload::text) <= 1048576"
            ),
            name=op.f("ck_execution_events_payload_object"),
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_execution_events_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_execution_events_node_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_execution_events_workflow_run_id_workflow_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_events")),
        sa.UniqueConstraint("workflow_run_id", "sequence", name="uq_execution_events_run_sequence"),
    )
    op.create_check_constraint(
        op.f("ck_execution_events_event_node_context"),
        "execution_events",
        "(event_type IN ('node.created', 'node.status_changed')) = (node_run_id IS NOT NULL)",
    )
    _install_guards()


def downgrade() -> None:
    op.drop_table("execution_events")
    op.drop_index("ix_node_runs_run_created_id", table_name="node_runs")
    op.drop_index(
        "ix_node_runs_one_open_attempt",
        table_name="node_runs",
        postgresql_where=sa.text("status IN ('pending', 'running', 'waiting_approval')"),
    )
    op.drop_table("node_runs")
    op.drop_index("ix_workflow_runs_workflow_created_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status_created_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_parent_run_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.execute("DROP FUNCTION guard_node_run_state()")
    op.execute("DROP FUNCTION guard_workflow_run_state()")
    op.execute("DROP FUNCTION reject_execution_event_mutation()")
    op.execute("DROP FUNCTION reject_execution_history_deletion()")


def _install_guards() -> None:
    op.execute("""
        CREATE FUNCTION reject_execution_history_deletion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Execution history cannot be deleted or truncated'
                USING ERRCODE = '23514';
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION reject_execution_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Execution events are immutable' USING ERRCODE = '23514';
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION guard_workflow_run_state() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE has_open boolean;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'queued' OR NEW.revision <> 0 OR NEW.event_sequence <> 0 THEN
                    RAISE EXCEPTION 'New runs must start queued at revision zero'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.workflow_id, NEW.workflow_version_id, NEW.parent_run_id,
                   NEW.trigger_type, NEW.input_json, NEW.created_at)
                IS DISTINCT FROM ROW(OLD.id, OLD.workflow_id, OLD.workflow_version_id,
                   OLD.parent_run_id, OLD.trigger_type, OLD.input_json, OLD.created_at) THEN
                RAISE EXCEPTION 'Run identity and input are immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.event_sequence < OLD.event_sequence
                OR NEW.event_sequence - OLD.event_sequence > 1 THEN
                RAISE EXCEPTION 'Invalid run event counter' USING ERRCODE = '23514';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF NOT ((OLD.status = 'queued' AND NEW.status IN
                           ('running', 'failed', 'cancelled'))
                    OR (OLD.status = 'running' AND NEW.status IN
                           ('waiting_approval', 'succeeded', 'failed', 'cancelled'))
                    OR (OLD.status = 'waiting_approval' AND NEW.status IN
                           ('running', 'failed', 'cancelled')))
                    OR NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION 'Invalid run state transition' USING ERRCODE = '23514';
                END IF;
                IF NEW.status IN ('succeeded', 'failed', 'cancelled') THEN
                    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.node_runs '
                        'WHERE workflow_run_id = $1 AND status IN '
                        '(''pending'', ''running'', ''waiting_approval''))', TG_TABLE_SCHEMA)
                        INTO has_open USING NEW.id;
                    IF has_open THEN
                        RAISE EXCEPTION 'Run has open node attempts' USING ERRCODE = '23514';
                    END IF;
                END IF;
            ELSIF NEW.revision <> OLD.revision OR ROW(NEW.started_at, NEW.completed_at,
                     NEW.output_json, NEW.error_code) IS DISTINCT FROM
                     ROW(OLD.started_at, OLD.completed_at, OLD.output_json, OLD.error_code) THEN
                RAISE EXCEPTION 'Run results require a legal state transition'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                RAISE EXCEPTION 'Run start time is immutable' USING ERRCODE = '23514';
            END IF;
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION guard_node_run_state() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE parent_status text; member boolean;
        BEGIN
            EXECUTE format('SELECT status FROM %I.workflow_runs WHERE id = $1 FOR UPDATE',
                TG_TABLE_SCHEMA) INTO parent_status USING NEW.workflow_run_id;
            IF parent_status IS NULL OR parent_status NOT IN ('running', 'waiting_approval') THEN
                RAISE EXCEPTION 'Node attempts require an active run' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'pending' OR NEW.revision <> 0 OR parent_status <> 'running' THEN
                    RAISE EXCEPTION 'New attempts must start pending in a running run'
                        USING ERRCODE = '23514';
                END IF;
                EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.workflow_runs r '
                    'JOIN %I.workflow_versions v ON v.workflow_id = r.workflow_id '
                    'AND v.id = r.workflow_version_id CROSS JOIN LATERAL '
                    'jsonb_array_elements(CASE WHEN jsonb_typeof(v.definition_json->''nodes'') '
                    '= ''array'' THEN v.definition_json->''nodes'' ELSE ''[]''::jsonb END) '
                    'AS n(node) WHERE r.id = $1 AND jsonb_typeof(n.node->''id'') = ''string'' '
                    'AND n.node->>''id'' = $2)', TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
                    INTO member USING NEW.workflow_run_id, NEW.node_id;
                IF NOT member THEN
                    RAISE EXCEPTION 'Node is not in the saved run definition'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.workflow_run_id, NEW.node_id, NEW.attempt_number,
                    NEW.input_json, NEW.created_at) IS DISTINCT FROM
                ROW(OLD.id, OLD.workflow_run_id, OLD.node_id, OLD.attempt_number,
                    OLD.input_json, OLD.created_at) THEN
                RAISE EXCEPTION 'Attempt identity and input are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF NOT ((OLD.status = 'pending' AND NEW.status IN
                           ('running', 'skipped', 'failed', 'cancelled'))
                    OR (OLD.status = 'running' AND NEW.status IN
                           ('waiting_approval', 'succeeded', 'failed', 'cancelled'))
                    OR (OLD.status = 'waiting_approval' AND NEW.status IN
                           ('running', 'succeeded', 'failed', 'cancelled')))
                    OR NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION 'Invalid node state transition' USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.revision <> OLD.revision OR ROW(NEW.started_at, NEW.completed_at,
                     NEW.duration_ms, NEW.output_json, NEW.error_code) IS DISTINCT FROM
                     ROW(OLD.started_at, OLD.completed_at, OLD.duration_ms,
                         OLD.output_json, OLD.error_code) THEN
                RAISE EXCEPTION 'Node results require a legal state transition'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                RAISE EXCEPTION 'Attempt start time is immutable' USING ERRCODE = '23514';
            END IF;
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER execution_events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON execution_events FOR EACH STATEMENT
        EXECUTE FUNCTION reject_execution_event_mutation()
    """)
    for table in ("workflow_runs", "node_runs"):
        op.execute(
            f"CREATE TRIGGER {table}_retain_history BEFORE DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION reject_execution_history_deletion()"
        )
    op.execute("""
        CREATE TRIGGER workflow_runs_state BEFORE INSERT OR UPDATE ON workflow_runs
        FOR EACH ROW EXECUTE FUNCTION guard_workflow_run_state()
    """)
    op.execute("""
        CREATE TRIGGER node_runs_state BEFORE INSERT OR UPDATE ON node_runs
        FOR EACH ROW EXECUTE FUNCTION guard_node_run_state()
    """)
