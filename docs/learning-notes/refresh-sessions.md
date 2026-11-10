# Refresh sessions, rotation and reuse detection — Phase 3C

Implemented on 30 October 2026, after [login/access JWTs](login-access-tokens.md). This increment adds persisted refresh families, one-use opaque token history, POST /api/v1/auth/refresh and browser cookie/CSRF delivery. Login now creates a family and sets cookies. Registration and header-only /auth/me keep their earlier roles. Logout and object ownership remain Phase 3D; frontend wiring remains later work.

Phase 3D now adds [logout and ownership dependencies](logout-ownership.md). The notes below record the 3C increment; logout is no longer pending, and database overrides now use the shared get_database_resource dependency.

## Design and policy

An access JWT is short-lived. A refresh credential obtains another access token without repeating password entry, so it must be protected, expiring and revocable. Each login creates a separate RefreshSession family. Its absolute expiry defaults to seven days; refresh does not extend it. Different logins for the same account remain separate families.

A refresh value is 32 random bytes encoded into 43 URL-safe characters. A second independent value provides CSRF proof. PostgreSQL stores only their SHA-256 digests. Fast hashing is appropriate for these high-entropy random values; human passwords still require Argon2. Refresh values are delivered only in cookies, never JSON, query strings, Bearer headers or application logs. The CSRF value is intentionally readable to same-origin JavaScript and returned as csrf_token in successful login/refresh JSON; it is not a credential by itself.

Every successful refresh consumes its presented token and inserts a new token/CSRF pair atomically. Retain consumed hashes to recognize old-token reuse. Replaying a known consumed token with its valid bound proof revokes its whole family, including later descendants, before returning 401. This pattern is informed by [RFC 9700 refresh replay guidance](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14); this app is not claiming a complete OAuth authorization-server implementation.

The family row is the shared lock for every generation. Locking only the presented token would not serialize an ancestor replay against a descendant rotation. Refresh reads the token by digest, locks its family with SELECT FOR UPDATE, then rereads the token with populate_existing to replace cached state after waiting. A partial unique index additionally permits only one unconsumed token per family. Revoked/expired families can still retain an unconsumed row; it is not usable merely because consumed_at is null.

## Cookies and CSRF contract

Default cookies:

| Cookie                   | Flags and purpose                                                                |
| ------------------------ | -------------------------------------------------------------------------------- |
| __Host-agentflow_refresh | Secure, HttpOnly, SameSite=Strict, Path=/, no Domain; opaque refresh credential  |
| __Host-agentflow_csrf    | Secure, readable, SameSite=Strict, Path=/, no Domain; copy into X-AgentFlow-CSRF |

The __Host- prefix requires Secure, root path and no Domain in supporting browsers; see [MDN cookie prefix rules](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie#cookie_prefixes). Root path also makes the CSRF cookie readable from application pages. HttpOnly prevents JavaScript from reading the refresh value, while the browser still attaches it to requests.

Both login and refresh require exactly one allowed Origin header and X-AgentFlow-Client: web. Missing/null/foreign/duplicate origins or absent/wrong client marker fail 403 before credential/database work. A browser sends Origin automatically; non-browser clients must send it explicitly. The marker makes cross-site form submissions insufficient even for login, which has no prior CSRF cookie. No permissive missing-Origin fallback is added. The initial supported browser flow is same-origin API/docs; cross-host frontend CSRF recovery remains part of later integration.

Refresh additionally requires X-AgentFlow-CSRF equal to the current readable CSRF cookie. The service compares its digest to the proof bound to the stored refresh token. A forged cookie/header pair matching itself still fails the server binding. This is stateful token binding, not a naive double-submit equality check or a claim that SameSite alone solves CSRF. See [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) for custom headers, Origin checks and session binding.

Bad CSRF never consumes/revokes tokens or clears cookies; otherwise a forged request could disrupt a valid session. Invalid/missing refresh credentials return 401 and delete the matching cookie pair only after Origin/client checks pass. Storage failures return 503 without clearing cookies, permitting a later retry if no rotation committed.

## Schema and migration

Revision **0002** depends on unchanged 0001. No new package or lockfile change is needed.

| Table            | Actual fields and constraints                                                                                                                                                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| refresh_sessions | UUID id (the family), user_id FK ON DELETE CASCADE, created_at, absolute expires_at, nullable revoked_at; expiry must exceed creation; indexes on user and expiry                                                                                       |
| refresh_tokens   | UUID id, session_id FK ON DELETE CASCADE, unique 64-character token_hash, 64-character csrf_hash, created_at, nullable consumed_at; lowercase hex checks on both digests, family lookup index and partial unique family index WHERE consumed_at IS NULL |

There is no raw token field, replacement raw-secret cache or JWT denylist. Every retained token points to its family, so a separate replaced_by chain is unnecessary for family-wide revocation. CASCADE removes refresh state when an account is deleted; existing workflow/history deletion restrictions remain unchanged. Expiry/history indexes prepare for retention work but do not run cleanup automatically.

0002 downgrade removes only refresh tables, signing out persistent refresh sessions while preserving users/workflows/versions. Tests use populated disposable schemas for downgrade; the development database only received the additive upgrade. API startup does not auto-migrate.

## Files and functions

Paths below are relative to backend/.

| File                                          | Responsibility and important calls                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| app/core/config.py                            | refresh_token_ttl_seconds bounds absolute family lifetime to 300–2592000 seconds; refresh_cookie_secure defaults true; auth_allowed_origins validates 1–10 exact HTTP(S) origins. Production refuses insecure cookies and requires HTTPS origins when JWT auth is configured. Malformed JSON origin configuration is mapped from SettingsError to a static ConfigurationError without its raw source. No wildcard, credentials, path, non-ASCII or whitespace origin values. |
| .env.example                                  | Documents explicit local HTTP switch, origin JSON array, TTL and required client/CSRF headers. Existing private .env is not edited.                                                                                                                                                                                                                                                                                                                                          |
| app/core/refresh_tokens.py                    | new_opaque_token uses secrets.token_urlsafe(32) wrapped in SecretStr; valid_opaque_token bounds and validates cookie syntax before hashing; token_digest computes SHA-256; frozen RefreshCredentials carries masked raw values internally.                                                                                                                                                                                                                                   |
| app/modules/auth/refresh_models.py            | RefreshSession/RefreshToken map families and retained consumed history with FK/check/index constraints.                                                                                                                                                                                                                                                                                                                                                                      |
| app/infrastructure/database/models.py         | Registers both mappings for all ORM consumers and Alembic metadata.                                                                                                                                                                                                                                                                                                                                                                                                          |
| migrations/versions/0002_refresh_sessions.py  | Explicit create/index/constraint operations; dependency-ordered downgrade; no create_all or edits to applied 0001.                                                                                                                                                                                                                                                                                                                                                           |
| app/modules/auth/refresh_repository.py        | create_session and add_token flush but never commit. find_token refreshes cached attributes; lock_session serializes by family; consume flushes the old row first to release the partial unique key before replacement INSERT.                                                                                                                                                                                                                                               |
| app/modules/auth/service.py                   | AuthResult carries public LoginResponse plus internal masked cookies/deadline. session_result creates the access JWT/public DTO inside the chosen transaction. login keeps Argon2 outside SQL, then inserts family/token and commits before returning. refresh locks/rereads, validates CSRF/current state, consumes/inserts/builds response or records revocation; only raises replay rejection after successful commit.                                                    |
| app/modules/auth/schemas.py                   | Adds csrf_token to LoginResponse, excluded from repr but intentionally serialized to the client. No raw refresh value enters a public model.                                                                                                                                                                                                                                                                                                                                 |
| app/modules/auth/exceptions.py                | CsrfError maps to safe 403; RefreshRejectedError specializes AuthenticationError so only rejected refresh requests delete their cookies.                                                                                                                                                                                                                                                                                                                                     |
| app/api/auth_cookies.py                       | cookie_names selects secure __Host- names or explicit dev names. set_auth_cookies applies flags/deadline/max-age to both values, converting DB timestamps to UTC for GMT expiry formatting. clear_auth_cookies deletes both with identical path/security settings.                                                                                                                                                                                                           |
| app/api/dependencies.py                       | require_auth_origin checks Origin/client marker. get_refresh_credentials reads only cookies, validates bounded syntax/header equality and returns masked credentials. get_settings provides per-app policy; existing access/Bearer/database dependencies retain their roles.                                                                                                                                                                                                 |
| app/api/v1/auth.py                            | Login/refresh call services in workers, set cookies only after commit, return public body and no-store/no-cache. Refresh documents no body credentials. Authentication handler clears cookies for RefreshRejectedError; csrf_handler preserves valid browser state on 403.                                                                                                                                                                                                   |
| app/main.py                                   | Updates the application description to the implemented refresh scope.                                                                                                                                                                                                                                                                                                                                                                                                        |
| tests/unit/test_refresh_config.py             | Random token/digest behavior, malformed credentials, origin rules, production flags and bounded TTL/private errors.                                                                                                                                                                                                                                                                                                                                                          |
| tests/api/test_refresh_contract.py            | Origin/client rejection, duplicate origins, no body/query/Bearer fallback, missing-cookie deletion, CSRF failure preservation, and OpenAPI contract without database access.                                                                                                                                                                                                                                                                                                 |
| tests/integration/test_refresh.py             | Real login/rotation/absolute expiry, stored digests, secure/dev cookies, CSRF binding, family replay/isolation, invalid states, replacement/signing failure rollback, login atomicity, storage recovery and log privacy.                                                                                                                                                                                                                                                     |
| tests/integration/test_refresh_concurrency.py | Independent PostgreSQL connections cache state before a barrier, then race same-token refresh or ancestor replay against current rotation. Family revocation remains durable; no two usable descendants. Bounded barrier/SQL deadlines avoid hanging tests.                                                                                                                                                                                                                  |
| tests/integration/test_refresh_models.py      | Database hash/FK/expiry/uniqueness guards and populated 0002→0001→0002 round trip preserving users with no metadata drift.                                                                                                                                                                                                                                                                                                                                                   |
| Existing login/health/schema/migration tests  | Update five-path inventory, successful csrf_token/cookie contract, required Origin/client headers, ORM table registry and head revision; previous security tests remain active.                                                                                                                                                                                                                                                                                              |

## Transaction flow and failure ownership

```text
Login with allowed Origin/client marker
  → read/close initial user Session → Argon2 verification outside SQL
  → unit of work: recheck user/hash → create family + hashed token/proof
      → build public access/CSRF response → commit
  → set browser cookies → return 200 (no-store/no-cache)

Refresh with allowed Origin/client marker + cookie/header proof
  → locate digest → lock family → reread token after waiting
  → validate server-bound CSRF proof
  → consumed: mark family revoked → COMMIT → reject 401 + clear cookies
  → revoked/expired/inactive: reject; inactive-family revocation commits
  → usable: consume/flush → insert replacement → build public response
      → COMMIT → set replacement cookies → return 200
```

Raising inside unit_of_work rolls back. Therefore replay revocation must leave that context normally, commit, and only then raise RefreshRejectedError. Conversely, replacement insert, response validation or signing failure must escape the context so both consumption and replacement roll back. The service never returns a new raw credential before its digest is committed.

An HTTP response cannot be atomic with a DB commit. If the server commits but the client loses the response, retrying the old pair is reuse and revokes the family. This policy deliberately has no grace window or raw-secret recovery cache. The client must require fresh login in this case rather than promise transparent recovery.

## Setup and observable API behavior

From backend/, after PostgreSQL startup:

```bash
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

Development was already upgraded through the guarded local Compose URL: current is **0002 (head)** and check reports no new upgrade operations. Existing account data was not changed. JWT key setup from the [backend guide](../../backend/README.md) still applies. Defaults allow API origins http://127.0.0.1:8000 and http://localhost:8000; use the same hostname consistently.

For local plain HTTP, explicitly set AGENTFLOW_REFRESH_COOKIE_SECURE=false in your private configuration and restart. Keep the true default for HTTPS; production rejects false. Override AGENTFLOW_AUTH_ALLOWED_ORIGINS with a JSON array of exact origins if using another port, and use HTTPS origins for configured production auth. Origin permission is not a CORS response header; cross-origin browser/frontend connection is still unimplemented.

In /docs, login with email/password and X-AgentFlow-Client set to web. The browser supplies Origin and stores cookies. Copy csrf_token from JSON (or the readable cookie) into the refresh endpoint's X-AgentFlow-CSRF field and set its client header to web. A successful refresh changes both cookies and returns the latest proof; /me continues using Authorization: Bearer with the access JWT. Non-browser clients must maintain a cookie jar and send Origin explicitly. Refresh body/query/Bearer values are ignored as credential sources.

| Outcome                                           | Response                                                                                                        |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Successful login/refresh                          | 200, access_token, csrf_token, bearer type, access expires_in, public user; no-store/no-cache; both cookies set |
| Missing/malformed/unknown/expired/revoked refresh | 401 UNAUTHENTICATED, safe envelope and Bearer challenge; both matching cookies deleted                          |
| Origin/client/CSRF failure                        | 403 FORBIDDEN, safe envelope; no cookie mutation or token consumption                                           |
| Storage/key unavailable                           | 503 SERVICE_UNAVAILABLE; no cookie deletion or successful response                                              |
| Unexpected insert/signing/mapping failure         | Safe 500; transaction rolls back if not yet committed; no new cookies                                           |

Every error carries request_id matching X-Request-ID; private reasons/token/hash/SQL values are omitted. A consumed-token replay with its valid proof revokes the family; an arbitrary unknown token cannot identify/revoke an unrelated session. Other login families continue normally.

## Verification and limitations

Full checker: **253 passed** with real PostgreSQL. Ordinary checker: **164 passed, 89 skipped** integration cases. Ruff lint/format passed 72 Python files; Pyright reported zero errors/warnings; locked offline sync passed. This adds 33 ordinary cases and 21 PostgreSQL cases; all previous checks remain green.

Same-token concurrency yields one replacement/one rejection, then the family is revoked; the apparent winner's refresh token cannot continue. Ancestor replay racing a descendant rotation also leaves the whole family revoked, whichever gets the lock first. Independent backend PIDs prove separate connections. Distinct login families are unaffected. Failure tests prove original-token consumption rolls back after insert/signing failure, replay revocation survives its 401, and storage recovery works without losing a still-valid cookie.

HTTP tests exposed PostgreSQL returning an aware timestamp with a different UTC tzinfo representation: cookie GMT formatting requires datetime.UTC. The cookie helper now normalizes the expiry; real rotation tests cover the path. Model/migration tests exercise actual PostgreSQL constraints and populated downgrade/re-upgrade, not just mocked SQL.

A real Uvicorn HTTP smoke used a disposable migrated schema, explicit dev HTTP cookies and a process-local key. It logged in, stopped the server, started a fresh process, refreshed successfully, checked profile access and missing-marker 403, replayed the old pair, and confirmed durable revocation rejected the child with cleared cookies. Five OpenAPI paths, request/log correlation, secret privacy and graceful shutdown passed. Temporary server/schema/container were cleaned up; development postgres remained running. No browser UI interaction or cross-origin browser acceptance test is claimed.

Clients must serialize refresh across requests/tabs; there is no overlapping-refresh grace period. Refresh-family revocation does not revoke already issued access JWTs, which remain bounded by their own expiry/current-account check. Password-reset/session invalidation, logout, retention cleanup/jobs, rate limits, device/session management, production lock deadlines, MFA and frontend wiring are later work. Consumed hashes must be retained through the family's usable lifetime for replay detection; no automatic deletion job is implemented. XSS can still make same-origin requests/read CSRF/access data; HttpOnly is not a complete XSS defense. This increment is not a public-deployment or OAuth-compliance completion claim.

Next: **Phase 3D — logout and ownership dependencies**, reviewing the proposed logout addition before implementation. Workflow APIs follow in Phase 4.

## Independent exercise

In the isolated test fixture, rotate twice, replay the original refresh/CSRF pair, then verify the newest refresh token fails in a fresh request while another login family still succeeds. Do not use development data. Leave the solution for your attempt.

## Review questions

Discuss these one at a time:

1. Why must replay revocation commit before the service raises its 401 outcome?
2. Why lock the family instead of only the token presented by a refresh request?
3. Why is cookie/header equality insufficient without checking the stored CSRF binding?
4. Why retain consumed hashes, and why do random refresh values use SHA-256 instead of Argon2?
5. What happens if a successful rotation commits but its HTTP response is lost?
