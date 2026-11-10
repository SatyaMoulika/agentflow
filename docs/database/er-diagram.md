# Proposed database ER diagram

Phase 0 target ER design. USERS, WORKFLOWS, and WORKFLOW_VERSIONS were implemented in revision 0001. Phase 3C revision 0002 adds REFRESH_SESSIONS (families) and REFRESH_TOKENS (retained one-use hash history); Phase 5A revision 0003 adds WORKFLOW_RUNS, NODE_RUNS and EXECUTION_EVENTS, with status revision, exact-version/attempt identity and ordered events. Lease/checkpoint/telemetry and other future fields in this target diagram remain planned; the implemented field inventory is in [execution persistence notes](../learning-notes/execution-persistence.md). Other entities remain planned. See [refresh-session notes](../learning-notes/refresh-sessions.md). See [model/migration notes](../learning-notes/migrations.md) for verified scope.

```mermaid
erDiagram
    USERS ||--o{ WORKFLOWS : owns
    USERS ||--o{ WORKFLOW_VERSIONS : creates
    USERS ||--o{ CONNECTIONS : owns
    USERS ||--o{ APPROVALS : receives
    USERS ||--o{ REFRESH_SESSIONS : authenticates
    REFRESH_SESSIONS ||--o{ REFRESH_TOKENS : rotates
    USERS ||--o{ IDEMPOTENCY_KEYS : scopes
    WORKFLOWS ||--o{ WORKFLOW_VERSIONS : versions
    WORKFLOWS o|--o| WORKFLOW_VERSIONS : current_pointer
    WORKFLOWS ||--o{ WORKFLOW_RUNS : executes
    WORKFLOW_VERSIONS ||--o{ WORKFLOW_RUNS : freezes_definition
    WORKFLOW_RUNS ||--o{ NODE_RUNS : attempts
    WORKFLOW_RUNS ||--o{ EXECUTION_EVENTS : records
    NODE_RUNS o|--o{ EXECUTION_EVENTS : annotates
    WORKFLOW_RUNS ||--o{ APPROVALS : pauses
    WORKFLOW_RUNS ||--o{ DISPATCH_OUTBOX : schedules
    WORKFLOW_RUNS ||--o{ IDEMPOTENCY_KEYS : identifies_request

    USERS {
        uuid id PK
        text email UK
        text password_hash
        text display_name
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }
    WORKFLOWS {
        uuid id PK
        uuid owner_id FK
        text name
        text description
        text status
        uuid current_version_id FK
        timestamptz created_at
        timestamptz updated_at
    }
    WORKFLOW_VERSIONS {
        uuid id PK
        uuid workflow_id FK
        integer version_number
        jsonb definition_json
        text schema_version
        uuid created_by FK
        timestamptz created_at
    }
    WORKFLOW_RUNS {
        uuid id PK
        uuid workflow_id FK
        uuid workflow_version_id FK
        uuid parent_run_id FK
        text trigger_type
        text status
        jsonb input_json
        jsonb output_json
        jsonb checkpoint_json
        text lease_owner
        timestamptz lease_expires_at
        bigint lease_generation
        bigint event_sequence
        timestamptz cancellation_requested_at
        timestamptz next_wake_at
        timestamptz started_at
        timestamptz completed_at
        text trace_id
        text error_summary
    }
    NODE_RUNS {
        uuid id PK
        uuid workflow_run_id FK
        text node_id
        integer attempt_number
        text status
        jsonb input_json
        jsonb output_json
        jsonb metadata_json
        timestamptz started_at
        timestamptz completed_at
        bigint duration_ms
        text trace_id
        text span_id
        text parent_span_id
        text error_code
        text error_message
    }
    EXECUTION_EVENTS {
        bigint id PK
        uuid workflow_run_id FK
        uuid node_run_id FK
        bigint sequence
        text event_type
        jsonb event_payload
        timestamptz created_at
    }
    CONNECTIONS {
        uuid id PK
        uuid owner_id FK
        text provider
        text connection_name
        text status
        text credential_reference
        jsonb configuration_json
        timestamptz created_at
        timestamptz updated_at
    }
    APPROVALS {
        uuid id PK
        uuid workflow_run_id FK
        text node_id
        uuid requested_by FK
        uuid assigned_to FK
        text status
        jsonb request_payload
        jsonb decision_payload
        timestamptz decided_at
        timestamptz created_at
        timestamptz expires_at
    }
    REFRESH_SESSIONS {
        uuid id PK
        uuid user_id FK
        timestamptz expires_at
        timestamptz revoked_at
        timestamptz created_at
    }
    REFRESH_TOKENS {
        uuid id PK
        uuid session_id FK
        text token_hash UK
        text csrf_hash
        timestamptz created_at
        timestamptz consumed_at
    }
    DISPATCH_OUTBOX {
        uuid id PK
        uuid workflow_run_id FK
        text dispatch_key UK
        text event_type
        jsonb payload
        integer attempts
        timestamptz available_at
        timestamptz claimed_until
        timestamptz published_at
        timestamptz created_at
    }
    IDEMPOTENCY_KEYS {
        uuid id PK
        uuid user_id FK
        text operation
        text key_hash
        text request_hash
        uuid workflow_run_id FK
        timestamptz created_at
        timestamptz expires_at
    }
```

## Reading the relationships

- **One-to-many:** one user owns many workflows; one workflow has many versions/runs; one run has many node-attempt rows, events, and approval records.
- **Optional one-to-one pointer:** a workflow has zero or one current version; a version is current for at most its own workflow. That pointer is separate from the one-to-many version history. It is nullable only during initial workflow creation or a deliberately versionless draft.
- **Exactly one referenced version per run:** an immutable version can be used by many runs. A composite foreign key verifies that the version belongs to the run's workflow.
- **Optional event association:** run-wide events have no node attempt. Node events reference an attempt belonging to the same run.
- **User roles in approvals:** the diagram shows the assignee relation. `requested_by` is also a user FK; service-created requests retain the initiating authorized user, not a fabricated agent user.
- **Infrastructure tables:** refresh sessions support revocation, dispatch outbox supports commit-safe job delivery, and idempotency keys deduplicate API run requests. These are justified additions to the eight application tables, introduced with Phases 3, 6 and 5 respectively.
- **LangGraph tables:** deliberately omitted from the application ERD. Its maintained PostgreSQL checkpointer owns separate tables/schema when introduced in Phase 8; node metadata records the thread correlation.

This is a relational design, not a request to create all tables in the first migration. See [schema decisions](schema.md) for constraints, indexes, migration order and transaction rules.
