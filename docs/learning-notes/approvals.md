# Owner approvals for pure workflows

An `approval` node saves its resolved input for the workflow owner to review. The worker commits the request, waiting attempt, waiting run and events together, releases its lease and exits. No worker or database transaction waits for a person.

This increment supports only graphs containing manual, transform, condition, calculator, JSON parser, merge, approval and end nodes. Background execution must be enabled. Validation rejects approval graphs containing Groq, agents, HTTP or Gmail. Email approval/actions require a later external-effect recovery policy. AI generation/edit proposals do not yet author approval graphs.

## Local setup

Apply the additive migration to the intended application database as an operator; no development migration was applied by the tests:

```bash
uv run --directory backend --locked alembic upgrade head
```

Start Redis, the API with background execution enabled, the worker and dispatcher as described in [background execution](background-execution.md). Preserve the private signing, database and encryption settings. The dispatcher also expires due approval requests; keep it running while approvals wait.

In the editor, add **Owner approval**, set its review title and expiration (60 seconds to seven days; default one day), and connect both `approved` and `rejected` routes. Save, validate and run. Open **Approvals**, inspect the saved input and exact execution/version, then approve or reject with an optional note. The run details link to pending requests.

For a minimal example, use this definition in the editor's JSON view:

```json
{
  "schema_version": "1.0",
  "nodes": [
    { "id": "start", "type": "manual", "config": {} },
    {
      "id": "review",
      "type": "approval",
      "config": { "title": "Review the submitted input", "expires_in_seconds": 86400 }
    },
    { "id": "accepted", "type": "end", "config": {} },
    { "id": "declined", "type": "end", "config": {} }
  ],
  "edges": [
    { "id": "a", "source": "start", "target": "review" },
    { "id": "b", "source": "review", "target": "accepted", "source_handle": "approved" },
    { "id": "c", "source": "review", "target": "declined", "source_handle": "rejected" }
  ]
}
```

The approval output is `{"decision":"approved"}` or `{"decision":"rejected"}`. Downstream nodes can explicitly map earlier node outputs to retain original business input. Rejection selects the rejected branch; successful execution of that branch still produces a succeeded run. Expiration fails the waiting attempt and run with `DEADLINE_EXCEEDED`. Cancellation resolves a pending request as cancelled and prevents resumption.

## API and recovery rules

- `GET /api/v1/approvals`: owner-scoped queue; `status` defaults to `pending`; optional `run_id`, bounded `page` and `page_size`.
- `GET /api/v1/approvals/{approval_id}`: owned request and its saved input. Queue listings omit business input.
- `POST /api/v1/approvals/{approval_id}/decision`: `{"decision":"approved","note":null}` or `rejected`; the optional note has a 2,000-character bound. No caller-supplied approver identity is accepted.

The run row serializes decisions, expiry and cancellation. Identical decision/note replay returns the retained decision; a different decision/note returns 409. A decision received after the deadline resolves to `expired` and returns that status without resuming. Missing or unowned requests return 404. Review the returned status after a lost response.

Decision, attempt result, run transition, ordered events and outbox resume intent commit in one transaction. The new worker reconstructs the selected route using committed outputs from the run's immutable version; earlier successful nodes are not rerun. Recovery discovery also finds a lost resume delivery. Duplicate transport messages cannot consume a pending request or overwrite a resolved decision. Application requests and decisions are retained, protected by owner checks, restrictive foreign keys and database guards; downgrade refuses retained approval history.

Approvals remain limited to the workflow owner. Teams, delegated reviewers, notifications, Gmail sending and reconciliation of uncertain external outcomes remain future work. Approval input and notes are retained application data, protected by the same ownership boundary as execution history.
