# AgentFlow development guide

## Project layout

- `src/api/` and `src/App.tsx` are the active React/TypeScript frontend. The older `src/pages/`, fixtures, store and simulator are unrouted prototype references; don't import demo data into real accounts.
- `backend/app/` is the active FastAPI backend. `backend/agentflow/` is an older, unintegrated reference draft.
- PostgreSQL migrations live in `backend/migrations/`; update SQLAlchemy metadata and add a new Alembic revision for schema changes. Do not edit applied revisions.
- `docs/backend-implementation-plan.md` and `docs/real-backend-walkthrough.md` describe the staged implementation and local setup. Update current documentation when behavior changes.

## Working conventions

- Preserve user changes and the private `backend/.env`; never print secrets, tokens, business payloads or connection strings. Do not overwrite an existing `.env` with the example.
- Use real backend data in the active frontend. Mark unavailable capabilities honestly. Preserve business JSON keys and immutable workflow/version history.
- Keep owner checks, transaction boundaries, idempotency and event/history writes explicit. Do not hold database transactions across broker, provider or node execution calls. Do not claim exactly-once processing or resume external side effects without reconciliation.
- Groq is planned for Phase 7 using a model available on the user's free plan; do not add a paid fallback or call the provider without the required configuration.
- Tests must use the guarded, disposable PostgreSQL/Redis test services; never use the development database for destructive tests, downgrades, fixture insertion or cleanup. Preserve development volumes and data.

## Checks

Run commands from the project root. For frontend changes use `npm test`, `npm run lint`, and `npm run build` as appropriate. For backend changes use `uv run --directory backend --locked python scripts/check.py`. Database and broker changes require isolated integration checks:

```bash
docker compose --profile test up -d --wait postgres_test redis_test
TEST_DATABASE_URL=postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test \
TEST_REDIS_URL=redis://127.0.0.1:16380/15 \
uv run --directory backend --locked python scripts/check.py --integration --redis-integration
```

Stop/remove only test services started for the task. Report skipped tests, unavailable browser verification and meaningful limitations accurately.
