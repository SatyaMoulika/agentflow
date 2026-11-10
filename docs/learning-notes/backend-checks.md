# Backend checks — Phase 1D

## What this increment owns

Development tooling owns this feature. Runtime routes, request flow, database schema, migrations, and transaction behavior are unchanged. Phase 1 foundation is complete. [Phase 2A](sqlalchemy.md) now adds optional real PostgreSQL checks via --integration; this document records the earlier tooling increment.

Run all foundation checks from the repository root:

```bash
uv run --directory backend --locked python scripts/check.py
```

Or from `backend/`:

```bash
uv run --locked python scripts/check.py
```

`uv sync --locked` installs the development dependencies by default. Pyright needs Node.js; this workspace already uses Node 22 for the frontend. The Python Pyright wrapper is community-maintained and can provision Node when none is found; that fallback may require a download outside the Python lockfile. Our checks used the existing Node **22.22.3**, Python **3.13.13**, Pyright **1.1.414**, and its transitive Python dependency nodeenv **1.11.1**. See [Pyright installation](https://github.com/microsoft/pyright/blob/main/docs/installation.md).

## Why three kinds of checks?

| Tool                              | Responsibility                                                                 | What it cannot establish                                                   |
| --------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| Ruff lint and format verification | Find selected source mistakes and enforce consistent formatting                | Correct request behavior or all type compatibility                         |
| Pyright                           | Analyze annotated Python types without executing app code                      | Runtime validation, database connectivity, or behavior hidden behind `Any` |
| Pytest                            | Execute the selected settings, HTTP, lifecycle, logging, and concurrency cases | Every possible input or all unimplemented integration behavior             |

Static types do not replace Pydantic validation: environment variables and HTTP bodies still arrive at runtime. Type checking can reject a wrong callback signature even when existing tests exercise only the valid dispatch path.

## Files and changes

| File                                                                                            | Purpose and important behavior                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/pyproject.toml`                                                                        | Adds dev-only `pyright>=1.1.414,<1.2` and `[tool.pyright]`. Includes `app`, `tests`, `scripts`; excludes the virtual environment and unintegrated `agentflow` drafts. Uses standard mode, the local `.venv`, Python 3.12 as the static minimum, and reports unnecessary ignore comments.                                                                                            |
| `backend/uv.lock`                                                                               | Pins Pyright 1.1.414 and nodeenv 1.11.1; runtime package versions are unchanged.                                                                                                                                                                                                                                                                                                    |
| `backend/scripts/check.py`                                                                      | `BACKEND_DIR` derives from the script location. `CHECKS` contains the four commands. `main() -> int` invokes each with `sys.executable -m`, fixes the working directory, prints progress, and returns immediately on a failed subprocess. The main guard converts its return value into process exit status. Arguments are lists, without a shell. No formatting fixes are applied. |
| `backend/app/core/exceptions.py`                                                                | Registered callbacks now accept `Exception`, matching Starlette's callback type, then narrow with `isinstance` assertions. HTTP status/message/header behavior is unchanged.                                                                                                                                                                                                        |
| `backend/tests/api/test_errors.py`, `test_lifespan.py`, `backend/tests/unit/test_middleware.py` | Read logger `extra` values from the record's metadata dictionary: `LogRecord` does not declare arbitrary attributes statically. Assertions still require the expected keys and values. The 500-record search uses `.get()` to skip records without status metadata.                                                                                                                 |
| `backend/tests/unit/test_config.py`                                                             | Uses pytest `monkeypatch` to configure a temporary dotenv source and restore it. This preserves precedence/disabled-file coverage while avoiding `_env_file` constructor keywords absent from Pydantic's synthesized static model signature.                                                                                                                                        |
| README files, implementation plan, HTTP notes, development log, these notes                     | Record scope, reproducible commands, outcomes, limits, and the next increment.                                                                                                                                                                                                                                                                                                      |

The `.env` and `.env.example`, frontend code, and legacy drafts were not edited. No production endpoint or schema changed. No custom settings constructor, broad diagnostic suppression, or type-ignore workaround was needed.

## Type compatibility at framework boundaries

A framework callback is typed to accept `Exception`. A function annotated to accept only `HTTPException` has a narrower parameter type, so it does not satisfy that general callback contract. The registered callback now accepts the general type, then checks the specific exception expected for that registration. This is type narrowing: inside the guarded code Pyright knows the exception has HTTP attributes.

Pydantic model constructors have generated signatures for model fields. The runtime BaseSettings constructor accepts additional source-control arguments such as `_env_file`, but Pyright does not expose them in this model's synthesized signature. Tests instead change `Settings.model_config` temporarily using the existing pytest isolation mechanism. This does not remove dotenv behavior or change production settings loading.

Dynamic metadata remains a deliberate boundary: reading `LogRecord.__dict__` is valid Python, but its values are dynamically typed. Standard mode does not make the whole codebase strictly typed. Unknown values and ASGI/framework state still need runtime checks/tests.

Configuration paths are relative to the configuration file. `pythonVersion = "3.12"` checks the declared minimum's syntax/type surface; the app/tests actually run on pinned Python 3.13.13. This does not prove runtime compatibility on 3.12. See [Pyright configuration](https://github.com/microsoft/pyright/blob/main/docs/configuration.md).

## Verification and failure behavior

The first Pyright run reported 14 errors: callback signatures, dynamic logging fields, and BaseSettings constructor keywords. Those were resolved without disabling the relevant diagnostics. An initially misspelled diagnostic option was corrected to `reportUnnecessaryTypeIgnoreComment`.

The complete check command passes from both backend and repository-root entry points: Ruff lint passes, 22 Python files meet formatting, Pyright reports **0 errors and 0 warnings**, and **45 tests pass**. No new unit tests were needed for a tooling wrapper; an actual temporary source probe tested its failure path instead. Assigning a string to an annotated integer caused Pyright to fail, the wrapper exited nonzero, and Pytest did not run. The probe was removed in `finally`; the clean check passed afterward.

The checker is local automation, not a configured remote CI service. Offline verification works here because Python packages and Node are already available. A fresh machine may require downloads. No live server, browser, frontend suite, database, migration, worker, provider, or telemetry check was run during Phase 1D; previous live HTTP results remain recorded under Phase 1C.

## Review questions

Discuss one at a time:

1. What can Pyright detect that a passing API test might miss?
2. Why must a callback that promises to accept `Exception` not require only `HTTPException`?
3. Why use `sys.executable -m` and an explicit working directory in the check script?
4. Why does a Python 3.12 static target not prove the tests passed on Python 3.12?

## Independent exercise and next increment

Temporarily add a tiny function annotated to return `int` that returns a string. Predict which check fails, run the combined command, and explain why Pytest is skipped. Fix or remove the function and restore a green check. Do not change `.env` or silence the type checker.

Phase 2A is now implemented: see [PostgreSQL/session notes](sqlalchemy.md). Phase 2B now adds [models/migrations](migrations.md) and includes migration Python files in the same checks. The current next increment is Phase 2C, repositories and transaction tests. Phase 1D itself did not start infrastructure.
