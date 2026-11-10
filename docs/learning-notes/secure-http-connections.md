# Phase 7E — protected HTTP connections

The [provider/authorized-generation continuation](provider-integration-hardening.md)
now adds explicit connection selection in AI proposals and safe provider usage/error
metadata. Current migration head is **0010**; the 0009 notes below describe the
initial connection-storage increment.

Integrations now creates, lists and revokes owned HTTP connections. Each connection
authorizes **one fixed public HTTPS endpoint**, using no authentication, a bearer
token or `X-API-Key`. The HTTP GET node selects a connection in the editor. Its
saved configuration contains only `connection_id`, never usable credentials.

This increment implements GET with JSON responses. Provider hardening and generated
connection selection are now implemented in the linked continuation. OAuth,
credential rotation, dynamic query parameters, mutating methods and reconciliation
remain separate work.

## Setup and use

1. Run `uv sync --directory backend --locked`. Cryptography supplies authenticated
   encryption; HTTPCore supplies the network backend for validated address pinning.
2. Run `uv run --directory backend --locked alembic upgrade head` and restart the
   API. Current head is **0010**; the configured development database was upgraded to head on 10 November 2026.
3. For authenticated connections, privately generate a Fernet key using the command
   in `backend/.env.example` and add `AGENTFLOW_CONNECTION_ENCRYPTION_KEY` to the
   existing private `backend/.env`. Preserve existing settings. Unauthenticated
   connections work without this key. No private runtime key was read or changed here.
4. Create a connection in **Integrations → HTTP connections**. Creating it does
   not contact the endpoint. Credentials are write-only and encrypted on the server.
5. Build manual → HTTP GET → end, select the connection, save, validate and run.
   Input can be `{}`; workflow input is not forwarded to the endpoint. A JSON response
   such as `{"CustomerID":42}` produces
   `{"status_code":200,"body":{"CustomerID":42}}`. Arrays/scalars also work inside `body`.
6. Inspect real persisted results/events. Revoking a connection removes its stored
   credential and blocks future calls while retaining its ID and earlier history.

Keep the encryption key stable and backed up separately from database access.
Changing it does not re-encrypt existing credentials. Create replacement connections
explicitly when credentials change; automatic rotation is not implemented.

## Boundaries and flow

Create validates static endpoint syntax and credential shape, then encrypts before
opening a storage transaction. Fernet's authenticated envelope includes owner and
connection IDs, preventing ciphertext copied between rows from granting access.
The response contains metadata, with no plaintext, ciphertext or secret reference.

The runner records the attempt, checks connection ownership/revocation, copies its
protected data and closes the database session. Decryption, DNS, TLS and response
reading run outside transactions. The normal short transaction then commits actual
results or static failure history. Untaken branches do not call their HTTP nodes.

The executor permits only HTTPS port 443, with certificate verification and original
Host/SNI preserved. All DNS answers must be public; mixed public/private answers are
rejected. The socket gets a validated numeric address, avoiding a second hostname
lookup. Private/loopback/link-local/multicast addresses, mapped/tunneled IPv6 and
known metadata/platform endpoints are blocked. Redirects, URL credentials, query
strings, fragments, Unix sockets and environment proxies are unavailable.

Requests use fixed Accept headers and the selected authentication header; they send
no workflow input, arbitrary headers or cookies. Only 2xx JSON responses are accepted,
with a 64 KiB limit. Compression, duplicate keys, nonfinite numbers, excessive nesting
and decoded strings/keys containing the usable credential fail without persistence.
Business keys retain their original spelling.

Socket operations use five-second timeouts and a shared twenty-second deadline.
DNS uses the operating system resolver: its blocking lookup is governed by the host
resolver configuration and cannot be interrupted by the socket deadline. Deployment
egress restrictions remain useful alongside application validation.

HTTP graphs remain synchronous even with background mode enabled. No transport
retries, automatic node retries, full-workflow retry command or worker recovery is
allowed for them. Reusing a committed command key returns the original run without
another call. Cancellation or a process crash cannot retract an issued request;
inspect history before creating a new command. Revocation cannot abort a request
already authorized and in progress.

## API and storage

All operations require an active authenticated owner; successful responses use no-store:

| Operation                                     | Result                                                                                 |
| --------------------------------------------- | -------------------------------------------------------------------------------------- |
| `POST /api/v1/connections`                    | 201 metadata/Location; strict name, endpoint, auth type and optional write-only secret |
| `GET /api/v1/connections?page=1&page_size=20` | Owned metadata including revoked records; page size 1–100                              |
| `GET /api/v1/connections/{id}`                | Metadata; missing/unowned both 404                                                     |
| `DELETE /api/v1/connections/{id}`             | Idempotent 204 revocation and encrypted credential removal                             |

Migration 0009 adds `connections`, an owner/list index, credential-state checks and
identity/revocation guards. Only revocation may update a connection; deletion,
truncation, identity changes and reactivation are refused. Downgrade refuses retained
connections or HTTP failure history. Prior workflow/run records remain unchanged.

Failures distinguish `CONNECTION_UNAVAILABLE`, `HTTP_TARGET_BLOCKED`,
`HTTP_REQUEST_FAILED` and `DEADLINE_EXCEEDED`, without upstream response bodies,
credentials or headers in error details. Workflow validation remains structural;
connection authorization and DNS are checked during execution.

AI generation cannot invent connection IDs. Users explicitly select active owned
connections for new proposals; edits also authorize existing saved bindings. Only
approved IDs may appear in HTTP configs. Execution checks owner and revocation again.

## Verification and next step

On 6 November 2026 the full backend checker passed **1203 tests** against isolated
PostgreSQL/Redis, Ruff lint/format (194 files) and Pyright with zero errors/warnings.
Frontend checks passed **130 tests**, lint, TypeScript and production build.
Only the Redis test service started by this task was stopped/removed afterward;
the pre-existing PostgreSQL test and development services were preserved.

Tests cover encryption/tampering/row binding, DTO/auth/metadata privacy, public and
mixed DNS answers, address pinning, TLS hostname preservation, redirects/proxies,
invalid/compressed/oversized responses, credential echoes, timeouts, owner isolation,
revocation, command replay, no transaction during HTTP execution, one-attempt
failures, database guards and populated migration round trips. Network responses
are stubbed; no real external endpoint or private credential is used. Browser visual
verification remains outstanding.

Provider failure/usage hardening and an owner-scoped catalog for reviewed generation
are implemented in the continuation. Mutating methods still require a side-effect
and reconciliation design before background recovery is considered.

References: [Fernet](https://cryptography.io/en/latest/fernet/),
[HTTPCore network backends](https://www.encode.io/httpcore/network-backends/),
[OWASP SSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html).

Exercise: create a connection to a public JSON endpoint you trust, run it once,
revoke it and start a new run. Predict the failed attempt and error code, then
compare histories without changing the original workflow version.
