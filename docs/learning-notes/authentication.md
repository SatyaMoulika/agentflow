# Registration and password hashing — Phase 3A

Current contract update (3 November 2026): RegisterRequest now accepts 8–128 characters, preserving the current schema edit; tests/OpenAPI/current guides agree. The original Phase 3A policy and verification described below used a 15-character minimum. See the [current backend guide](../../backend/README.md#registration--phase-3a).

Implemented on 30 October 2026. This increment adds registration to the Phase 2 repositories and transaction contexts. It creates an account without issuing login credentials. Login/access JWTs belong to 3B; refresh sessions/rotation and browser cookie/CSRF rules follow in 3C. No schema change is required: users.password_hash and uq_users_email already exist in revision 0001.

Phase 3B now extends this module with [login and access tokens](login-access-tokens.md). These notes describe the registration increment; the linked notes explain the shared email schema refactor and current auth scope.

## Design and new concepts

A password hash is a one-way verifier, not encrypted plaintext. Argon2id uses time and memory to increase guessing cost; a fresh random salt prevents identical passwords from producing identical stored hashes. The encoded result records its algorithm, parameters, salt and digest so a later login can verify it. It remains sensitive and is never part of UserResponse.

We explicitly select argon2-cffi's RFC_9106_LOW_MEMORY profile: Argon2id, 65,536 KiB (64 MiB) memory, three iterations, four lanes, 16-byte salt and 32-byte hash. These are fixed policy parameters, not an assumption about whichever defaults a future release selects. Benchmark resource budgets and bound request rates before public deployment. See the library's [parameter guidance](https://argon2-cffi.readthedocs.io/en/stable/parameters.html) and [hash/verify API](https://argon2-cffi.readthedocs.io/en/stable/api.html).

SecretStr protects model representations and JSON dumps by masking its value. It does not hash, encrypt or erase memory. Only hash_password explicitly retrieves plaintext for the hashing library. Inputs and exception text must still stay out of logs. Request schemas hide validation input, and the existing HTTP handler returns static errors with null details.

The service owns the operation; the repository knows only persistence. An HTTP handler delegates to AuthService, which hashes before opening a unit of work, inserts through UserRepository, constructs an explicit public DTO inside the transaction, then returns after commit. Failed DTO construction, insert, or commit must not leave partial success.

A pre-insert email lookup cannot prevent two concurrent signups. The database unique constraint is authoritative. Catch IntegrityError outside the unit of work so rollback and closure have already occurred. Only SQLSTATE 23505 with constraint name uq_users_email becomes EmailAlreadyRegisteredError. Unrelated integrity errors propagate to the safe internal-error boundary.

## Files and important calls

Paths below are relative to backend/ except the documentation links.

| File                                    | Responsibility and important functions                                                                                                                                                                                                                                                                                                                                            |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| app/core/security.py                    | Builds one PasswordHasher from RFC_9106_LOW_MEMORY. hash_password(SecretStr) extracts the exact password and calls hash(); each call creates its own random salt. No login/verify helper is added yet.                                                                                                                                                                            |
| app/modules/auth/schemas.py             | RegisterRequest forbids extras, requires strict strings and bounds lengths. trim_public_fields trims only email/name; normalize_email selects lowercase identity; reject_blank_password rejects all-whitespace without changing accepted passwords. UserResponse selects public fields from ORM attributes with model_validate and serializes aware timestamps in UTC via as_utc. |
| app/modules/auth/service.py             | AuthService.register hashes first, opens Database.unit_of_work, calls UserRepository.add and builds UserResponse. Exiting the context commits before returning. It translates only the named email uniqueness violation, and maps OperationalError/pool TimeoutError to a storage outcome.                                                                                        |
| app/modules/auth/exceptions.py          | Plain EmailAlreadyRegisteredError and AuthStorageUnavailableError distinguish business/storage outcomes without SQLAlchemy or FastAPI dependencies.                                                                                                                                                                                                                               |
| app/api/dependencies.py                 | Async get_database resolves the shared engine owner from request.app.state. No configured Database means safe HTTP 503. It does not create or pass a Session across threads.                                                                                                                                                                                                      |
| app/api/v1/auth.py                      | Sync register_user delegates to the service, sets no-store, and returns 201. Router describes schemas/statuses. email_conflict_handler and storage_unavailable_handler map plain outcomes to the shared envelope; register_auth_exception_handlers installs them.                                                                                                                 |
| app/core/exceptions.py                  | Existing error_response accepts an optional trusted static public_error pair, used for the duplicate-email code/message. It never receives raw DB/validation messages.                                                                                                                                                                                                            |
| app/api/router.py, app/main.py          | Mount the auth router under /api/v1 and register module error handlers; update the API description. Existing health behavior remains intact.                                                                                                                                                                                                                                      |
| app/modules/auth/**init**.py            | Updates the module's scope description.                                                                                                                                                                                                                                                                                                                                           |
| pyproject.toml, uv.lock                 | Add argon2-cffi 25.1.0 and email-validator 2.3.0, required by EmailStr; existing dependencies remain locked.                                                                                                                                                                                                                                                                      |
| tests/unit/test_password_hashing.py     | Uses genuine hashes to check random salts, encoded RFC parameters, exact-password verification and rejection of a trimmed password.                                                                                                                                                                                                                                               |
| tests/unit/test_registration_schemas.py | Checks trimming/case rules, unchanged passwords, Unicode/length boundaries, strict/extra-field rejection, masked secrets and public UTC fields.                                                                                                                                                                                                                                   |
| tests/api/test_registration_contract.py | Checks missing storage, safe validation errors, request IDs, documented errors, password writeOnly schema and exact public fields without DB I/O.                                                                                                                                                                                                                                 |
| tests/api/test_health.py                | Updates the route inventory to health plus registration while retaining health's original response contract.                                                                                                                                                                                                                                                                      |
| tests/integration/test_registration.py  | Uses the real HTTP boundary, hashing, service, transactions and isolated PostgreSQL. Covers success, duplicate/race, unrelated integrity failures, storage recovery and response-construction rollback.                                                                                                                                                                           |

The **engine owner** can be shared. Its mutable ORM Session cannot. FastAPI runs the synchronous route in a worker thread; hashing and all Session work execute there. The async dependency returns only the engine owner. Tests observe actual hash/transaction thread IDs and prove hashing happened before the transaction began.

## Request and transaction flow

```text
POST /api/v1/auth/register
  → request middleware allocates request ID
  → resolve Database and validate RegisterRequest
  → worker thread: AuthService.register
      → hash exact password with Argon2id (no open SQL transaction)
      → Database.unit_of_work begins operation-local transaction
          → UserRepository.add → INSERT/flush → UUID/defaults
          → construct UserResponse from explicit public fields
      → normal context exit commits and closes Session
  → return 201 public DTO, no-store, X-Request-ID
  → completion record with the same request ID
```

Failure paths:

- Bad input: 422 VALIDATION_ERROR, null details, no input echoed. When no Database is configured, dependency resolution can instead return 503 first.
- Duplicate normalized email: rollback/close, plain email-conflict outcome, HTTP 409 EMAIL_ALREADY_REGISTERED.
- Connection or pool unavailability: rollback/close, storage outcome, HTTP 503 SERVICE_UNAVAILABLE.
- Unrelated integrity failure or mapping bug: rollback/close and safe HTTP 500 INTERNAL_ERROR. Never label every IntegrityError as a duplicate.
- Hashing failure: no SQL transaction has started; unexpected failure follows the safe 500 boundary.

Request IDs connect a response to logs; they do not grant access. Existing middleware omits request bodies, SQL text/parameters and raw exception messages from application completion records.

## Implemented input/output contract

POST /api/v1/auth/register is public and requires exactly these string fields:

| Field        | Policy                                                                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| email        | Trim, EmailStr syntax validation, lowercase account identity; max 320 characters, with the validator's own email limits also applying. No DNS/deliverability check. |
| display_name | Trim, then 1–100 characters. No roles/permissions inferred from the name.                                                                                           |
| password     | 15–128 Unicode characters; reject all-whitespace, otherwise preserve spaces/case exactly. No character composition rules or truncation.                             |

No is_active, password_hash, user ID, role or other privilege field is accepted. HTTP 201 returns only id, email, display_name, is_active, created_at and updated_at. UUIDs are strings, timestamps are aware UTC ISO 8601. Passwords/hashes are excluded by the explicit output schema. Cache-Control is no-store; there is no Set-Cookie or access/refresh token.

Duplicate 409 intentionally discloses that the address is registered. All errors use the existing envelope with details: null and request_id matching X-Request-ID. OpenAPI exposes only health and registration as application paths. The [API inventory](../api/endpoints.md) distinguishes implemented contracts from proposed routes.

## Verified behavior

Full backend checker: **136 passed** against real PostgreSQL; Ruff lint/format passed for 57 Python files; Pyright reported zero errors/warnings. Ordinary checker: **80 passed, 56 skipped** integration cases. Locked offline synchronization passed. Run commands are in the [backend guide](../../backend/README.md).

Six new integration cases exercise real registration success, normalized duplicate 409, unrelated integrity 500, storage 503 followed by recovery, response DTO failure rollback, and concurrent duplicate signup. The race synchronizes hashing before either transaction and proves one commit/one mapped conflict with exactly one account. DTO failure injects a naive datetime after INSERT, so it violates AwareDatetime without violating the ORM attribute's Python type. Existing migration/constraint/repository tests continue to pass.

The test harness substitutes only an already-migrated Database resource in a guarded random schema. Production routing, schemas, service, hashing and SQL execute normally. HTTPX ASGI tests do not themselves start a server or lifespan; those aspects have separate checks.

A temporary real local Uvicorn server also verified health 200, registration 201, duplicate 409, invalid input 422, the two-route OpenAPI inventory, matching response/log request IDs, no password/hash leakage and graceful shutdown. Its database resource targeted a disposable migrated test schema. Test data, schema, factory and server were removed afterward. No account was created in the development database, no private .env was changed, and no migration/frontend/build artifact/legacy-draft changes were required.

## Limits and next increment

Registration alone does not authenticate subsequent requests. Login, access-token signing/validation, /auth/me, session revocation/refresh, ownership dependencies and frontend connection are still pending. Email syntax validation does not prove mailbox ownership. There is no verification email, breached-password blocklist, recovery flow, rate limit, bounded hashing queue or production capacity benchmark. This is not a public-deployment completion claim or a claim of NIST compliance.

Argon2's memory cost is per concurrent hash. A synchronous worker protects the event loop but does not itself prevent resource exhaustion. Passwords are not Unicode-normalized; future verification must use exactly the policy used here. Future APIs must continue deriving ownership from validated authenticated identities rather than client-supplied IDs. No Groq key/model call is needed for this increment.

Next: **Phase 3B — login, access JWTs and /auth/me**. Design token algorithm/key requirements and expiry/claims first, then test correct/incorrect credentials, inactive users and expired/malformed tokens before moving to refresh rotation.

## Independent exercise

Using repository_database in an isolated PostgreSQL test, force the first registration to fail after INSERT, restore normal behavior, and register the same email successfully. Verify in a fresh unit of work that exactly one account was committed. Do not use development data. Leave the solution for your attempt.

## Review questions

Discuss these one at a time:

1. Why should password hashing happen before opening the database transaction?
2. Why does a pre-insert email lookup fail to prevent simultaneous duplicate registrations?
3. How do SecretStr, Argon2id, and UserResponse protect different parts of the credential flow?
4. Why must AuthService catch the uniqueness failure outside the unit-of-work context?
5. Why does a 201 registration response not make /auth/me possible yet?
