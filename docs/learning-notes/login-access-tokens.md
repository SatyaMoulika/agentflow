# Login and access JWTs — Phase 3B

Implemented on 30 October 2026. This increment adds JSON login and authenticated current-user lookup to [registration](authentication.md). It adds PyJWT 2.15.1, one token utility and focused tests. No database fields/migration, private .env, frontend/build artifacts or legacy drafts are changed. Revision remains 0001.

Phase 3C now extends this flow with [refresh sessions and bound CSRF cookies](refresh-sessions.md), adds csrf_token to successful responses, and requires Origin/client headers for login. The notes below describe the Phase 3B increment; use the linked notes/backend guide for the current cookie contract.

## Design before implementation

Authentication answers who a request represents; authorization decides which operations that identity may perform. This increment establishes a current active user. It does not expose workflow CRUD or complete owner/approver authorization.

A JWT is a signed collection of claims. Its signature protects integrity, not confidentiality: anyone holding it can decode its payload. Keep passwords, hashes, signing secrets, account details and arbitrary roles out of claims. A Bearer credential grants its holder access, so application responses/logs must not accidentally retain it.

For this single-backend increment, fixed HS256 uses one private random key to sign and verify. The application, not an untrusted token header, selects the allowed algorithm. All API processes must share the same private key and agree on issuer/audience/time. There is no default key or fallback accepting unsigned tokens. A future multi-service design may justify asymmetric signing/key management; it is not needed here.

We require sub (canonical UUID account ID), iss, aud (one exact audience), iat, nbf, exp (integer seconds), jti (canonical UUID token identifier), and token_type: access. Header typ must be at+jwt; unsupported critical extensions fail. Default lifetime is 900 seconds, configurable within 60–3600. nbf equals iat, expiry must be later and within the configured lifetime; future issue/not-before and expired credentials fail with zero clock leeway. Encoded token input is bounded to 8192 characters before decoding. See PyJWT's [signature and required-claim API](https://pyjwt.readthedocs.io/en/stable/api.html), including its fixed-algorithm guidance. Merely requiring a claim to exist does not validate every application-specific meaning, hence the UUID/type/purpose/lifetime checks.

Passwords are verified by Argon2 against the stored hash; they are never compared to stored plaintext or rehashed for equality. Salted hashes differ for the same password. Unknown emails still execute a real check against a public, non-account dummy hash. Even matching that dummy's known plaintext cannot authenticate a nonexistent account. This reduces an obvious cost difference, but does not guarantee constant-time network responses or prevent enumeration by registration's explicit 409. See [argon2 verification behavior](https://argon2-cffi.readthedocs.io/en/stable/api.html).

## Files and functions

Paths are relative to backend/.

| File                                                    | Changes and important calls                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| app/core/config.py                                      | Adds optional SecretStr jwt_secret_key, issuer, audience and bounded access_token_ttl_seconds. reject_key_whitespace runs before global settings trimming; validate_signing_key checks UTF-8 byte length. load_settings continues sanitizing errors. Missing key does not prevent health/registration.                                                                                                                      |
| .env.example                                            | Documents private key generation and optional issuer/audience/lifetime values without publishing a usable signing key. No real .env is read/edited by tests or this implementation.                                                                                                                                                                                                                                         |
| app/core/security.py                                    | verify_password accepts a SecretStr plus stored hash or None; calls the configured PasswordHasher.verify, substitutes a dummy for unknown accounts, rejects mismatch/corruption and never authenticates the dummy. Existing hash_password is unchanged.                                                                                                                                                                     |
| app/core/tokens.py                                      | AccessTokens.issue creates bounded, purpose-specific claims and calls jwt.encode with fixed HS256. subject bounds input and calls jwt.decode_complete with the fixed algorithm, issuer/audience and required claims, then checks application types/purpose/UUID/lifetime/header. InvalidAccessTokenError exposes no underlying parser details.                                                                              |
| app/modules/auth/schemas.py                             | Shares strict email input normalization in _EmailInput. LoginRequest requires only email/password; password is 1–128 characters, untrimmed. Registration keeps its 15-character minimum and blank rejection. LoginResponse explicitly selects access_token, bearer token_type, expires_in and UserResponse; token is excluded from repr, not from its intended HTTP serialization.                                          |
| app/modules/auth/service.py                             | login reads account ID/hash in one closed Session, verifies outside the read transaction, rechecks existence/active state/unchanged hash in a fresh Session, builds the public DTO, and only then issues a token. current_user reads by validated UUID and requires an active account on each call. Storage failures map to the existing module outcome. register remains transactional.                                    |
| app/modules/auth/exceptions.py                          | Adds plain AuthenticationError shared by wrong/unknown/inactive/deleted credentials; generalizes the private storage error message.                                                                                                                                                                                                                                                                                         |
| app/api/dependencies.py                                 | HTTPBearer(auto_error=False) documents the scheme. get_access_tokens obtains validated per-app configuration or returns 503. get_access_subject requires the header, validates the token and returns its UUID; bad credentials produce a safe 401 challenge. Sync get_current_user runs service SQL in a worker and returns a DTO, never an ORM Session. Existing get_database still resolves only the shared engine owner. |
| app/api/v1/auth.py                                      | Adds sync login_user and read_current_user, response schemas and shared 200/401/503 documentation. Login documents its safe 422 body error. Sets no-store, with no-cache on login. authentication_handler maps module AuthenticationError to the same safe 401 and Bearer challenge as the dependency. Public register behavior is preserved.                                                                               |
| app/main.py                                             | Describes the current auth scope. Auth handlers were already registered by the factory.                                                                                                                                                                                                                                                                                                                                     |
| app/modules/auth/repository.py, **init**.py             | Refresh scope comments; exact queries/schema remain unchanged.                                                                                                                                                                                                                                                                                                                                                              |
| pyproject.toml, uv.lock                                 | Add/lock PyJWT 2.15.1, no additional transitive dependencies.                                                                                                                                                                                                                                                                                                                                                               |
| tests/unit/test_access_tokens.py                        | Real signatures and modified signed claims test the trust boundary: expiry/future dates, wrong key/algorithm/issuer/audience/purpose, missing claims, malformed/oversized credentials, UUID/date types and unsupported header.                                                                                                                                                                                              |
| tests/unit/test_auth_config.py                          | No default key; parsed env/lifetime settings; masked key; invalid short/oversized/whitespace keys, issuer/audience and lifetime rejected without values in errors.                                                                                                                                                                                                                                                          |
| tests/unit/test_password_hashing.py                     | Genuine verify success, exact-space mismatch, unknown account including dummy plaintext, and corrupt-hash rejection.                                                                                                                                                                                                                                                                                                        |
| tests/api/test_login_contract.py                        | Header-only Bearer auth, no URL/cookie credential acceptance, missing key 503 with health available, strict safe 422 input, JSON-login/OpenAPI security contracts.                                                                                                                                                                                                                                                          |
| tests/api/test_health.py, test_registration_contract.py | Update exact application-path inventory to four while preserving earlier health/registration contracts.                                                                                                                                                                                                                                                                                                                     |
| tests/integration/test_login.py                         | Real hashes/signatures/HTTP/PostgreSQL; separate identities, safe credential failures, worker/pool observation, current-state checks, hostile tokens, changed status/hash during verification, storage failure/recovery and privacy.                                                                                                                                                                                        |

## Observable flows

```text
POST /api/v1/auth/login (public JSON)
  → middleware assigns request ID
  → resolve configured engine owner and signing policy; validate input
  → worker thread: read normalized email → copy ID/hash → close read Session
  → verify exact password with Argon2 (dummy check when email unknown)
  → wrong/unknown: shared AuthenticationError → safe 401 + Bearer challenge
  → fresh read: require account exists, active, unchanged hash → public user DTO
  → close Session → sign access token → 200 + no-store + no-cache
  → completion log omits credentials/token/key

GET /api/v1/auth/me
  → require Authorization Bearer header (no URL/cookie fallback)
  → verify signature and all token policy → validated UUID
  → sync dependency in worker: fresh account read → require active → public DTO
  → 200 + no-store, or shared safe 401/503 envelope
```

A SQL SELECT starts a transaction even for a read. Closing that Session before expensive Argon2 releases the connection/transaction while CPU/memory work proceeds. The login route and its Sessions stay in a worker thread. `/me`'s SQL runs in a synchronous dependency; only a public DTO crosses back to the handler. The small bounded HMAC/token checks do not perform database or Argon2 work on the event loop.

The recheck reduces races where a password/account changes during slow verification. It does not lock an account for the whole lifetime of a token. `/me` independently checks current active/existence state. The service has no stored session or last-login write in this increment.

## API and setup

From backend/, generate a **private local** signing key:

```bash
uv run --locked python -c 'import secrets; print(secrets.token_hex(32))'
```

Save the generated value locally as AGENTFLOW_JWT_SECRET_KEY in your gitignored .env, then restart the API. The validator requires 32–4096 UTF-8 bytes and no outer whitespace; it cannot prove entropy. Do not reuse fixture/example keys. Default issuer is agentflow, audience agentflow-api, lifetime 900 seconds. Override via AGENTFLOW_JWT_ISSUER, AGENTFLOW_JWT_AUDIENCE and AGENTFLOW_ACCESS_TOKEN_TTL_SECONDS if needed. Existing PostgreSQL configuration/migration is still required.

Login accepts JSON email/password, not an OAuth2 form or display_name. The login password minimum is one character so a short incorrect password reaches the same credential failure rather than registration's new-password policy. Empty/oversized/non-string passwords and extra fields remain 422. Accepted spaces/case are preserved exactly.

HTTP 200 login returns access_token, token_type: bearer, expires_in, and user with the public registration fields. It issues no refresh token/cookie. In Swagger choose Authorize, paste the returned JWT, then call /api/v1/auth/me. The header is Authorization: Bearer followed by the token. JSON Web Tokens are reusable Bearer credentials; never put them in URLs or logs.

Wrong/unknown/inactive credentials and malformed/expired/deleted-user tokens all return 401 UNAUTHENTICATED, message Authentication is required., details null, a matching response/header request ID, and WWW-Authenticate: Bearer. No reason/account-state detail is disclosed. Missing key/unavailable storage returns 503 SERVICE_UNAVAILABLE; configuration dependencies can precede login body validation. /me without a Bearer credential returns 401 before key/DB lookup. Unexpected failures stay safe 500. See [API contracts](../api/endpoints.md).

## Actual verification

Full checker: **199 passed** against real PostgreSQL; ordinary checker: **131 passed, 68 skipped**. Ruff lint/format passed for 62 Python files; Pyright reported zero errors/warnings. Locked offline synchronization passed. All prior migration/registration/repository checks remain green. New coverage comprises 51 ordinary cases and 12 real PostgreSQL cases.

Integration checks prove two users receive distinct current-user identities, normalized email login works, exact-space verification matters, unknown email still calls real verification, inactive accounts fail identically, and valid tokens fail after account disable/delete. They cover bad signature, expired/refresh-purpose/missing-subject credentials, changed account/hash during verification, and safe storage failure followed by recovery. Pool observations compare against the fixture's existing migration connection and prove login retains no extra checked-out connection during verification; thread observations prove worker execution. Tokens, hashes and passwords remain absent from logs and profile/error output. The token appears only in its intended successful login response.

A real temporary Uvicorn HTTP smoke also passed register 201, login/profile 200, missing/wrong credentials 401, deactivated-token 401, four OpenAPI paths, no-store/no cookie, request/log ID correlation, secret/key/token/hash privacy and graceful shutdown. It used the real app with only its Database resource targeting an isolated migrated test schema and a process-local random signing key. No development account/configuration was changed. Temporary server/schema/test container were cleaned up and development postgres left running.

Testing caught a settings subtlety: global str_strip_whitespace trimmed a raw secret before an after-validator could reject outer spaces. The added before-validator now rejects that input instead of silently changing a signing key. A test also narrowed SQLAlchemy's generic Pool type to QueuePool before checking its actual checkout count; no type suppressions were used.

## Limits and next increment

This completes access-token authentication, not production session management. No refresh/rotation/reuse detection, logout/revocation, password reset/version-based token invalidation, rate limiting, MFA, mailbox verification, browser cookie/CSRF/CORS integration or frontend auth connection exists yet. No provider call is needed. There is no keyring/asymmetric key rotation or automatic hash-parameter upgrade; the fixed current Argon2 profile is verified and existing hashes are not rewritten by login.

jti distinguishes issuance but is not stored or checked for replay. A stolen valid active-account token can be reused until expiry. Password changes after issuance do not revoke earlier tokens; disabling/deleting the account does make /me reject them. Reactivating an account can make a still-unexpired token usable again. Rotating the sole key invalidates old tokens globally; reducing configured lifetime can reject older tokens with longer encoded lifetimes. Account-state checks do not themselves enforce object ownership on future routes.

HMAC keys must be random/private and shared consistently across instances; clocks must be synchronized because validation has zero leeway. HS256 verifiers can also sign, so this is not a separate public-verifier architecture. Dummy hashing is not a substitute for rate/capacity controls. Future cookie refresh and CSRF rules need explicit design before adding sessions.

Next: **Phase 3C — persisted refresh sessions, rotation and reuse detection**, including its migration and real concurrent/replay/expiry/revocation checks. Browser delivery/CSRF must be designed first. Ownership/logout remain the next separately scoped increment.

## Independent exercise

Using the isolated repository_database fixture, register/log in, update display_name in a separate transaction, then call /auth/me with the original token. Verify it returns the updated name. Do not use development data. Leave the solution for your attempt.

## Review questions

Discuss these one at a time:

1. Why should /auth/me query the current account after it has verified a JWT signature?
2. Why must the server choose allowed algorithms instead of trusting the token's alg header?
3. Why is the initial read Session closed before password verification?
4. What does jti provide here, and why does it not prevent token replay?
5. Why are login passwords verified exactly instead of hashing the supplied password and comparing hash strings?
