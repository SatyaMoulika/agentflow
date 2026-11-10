"""Test-only routes exercise production authentication and scoped ownership dependencies."""

from threading import get_ident
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.api.workflow_dependencies import get_owned_workflow, get_owned_workflow_version
from app.core.config import Settings
from app.core.security import hash_password
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import User
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.workflows.access import OwnedWorkflow, OwnedWorkflowVersion
from app.modules.workflows.repository import WorkflowRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-ownership-signing-key-at-least-32-bytes"


def tokens() -> AccessTokens:
    return AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )


def probe_app(database: Database) -> FastAPI:
    application = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return database

    application.dependency_overrides[get_database_resource] = resource

    # These probes are declared only in tests, never mounted on create_app().
    @application.get("/_test/workflows/{workflow_id}")
    def workflow(reference: Annotated[OwnedWorkflow, Depends(get_owned_workflow)]) -> OwnedWorkflow:
        return reference

    @application.get("/_test/workflows/{workflow_id}/versions/{version_id}")
    def version(
        reference: Annotated[OwnedWorkflowVersion, Depends(get_owned_workflow_version)],
    ) -> OwnedWorkflowVersion:
        return reference

    return application


@pytest.fixture
def state(repository_database: Database) -> dict[str, UUID]:
    password_hash = hash_password(SecretStr("private ownership fixture password"))
    result: dict[str, UUID] = {}
    with repository_database.unit_of_work() as session:
        users = UserRepository(session)
        workflows = WorkflowRepository(session)
        for label in ("a", "b"):
            user = users.add(
                email=f"{label}@example.com", password_hash=password_hash, display_name=label
            )
            workflow = workflows.add(owner_id=user.id, name=f"private workflow {label}")
            version = workflows.append_version(
                workflow_id=workflow.id,
                owner_id=user.id,
                expected_version=0,
                definition={"schema_version": "1.0", "nodes": [], "edges": [], "private": label},
            )
            result.update(
                {
                    f"user_{label}": user.id,
                    f"workflow_{label}": workflow.id,
                    f"version_{label}": version.id,
                }
            )
        extra = workflows.add(owner_id=result["user_a"], name="Another owned workflow")
        result["extra_workflow"] = extra.id
    return result


def path(state: dict[str, UUID], label: str, *, version: bool) -> str:
    base = f"/_test/workflows/{state[f'workflow_{label}']}"
    return base + f"/versions/{state[f'version_{label}']}" if version else base


@pytest.mark.parametrize("version", [False, True])
async def test_two_users_can_access_only_their_own_workflow_or_version(
    repository_database: Database,
    state: dict[str, UUID],
    version: bool,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=probe_app(repository_database)), base_url="https://test"
    ) as client:
        for actor, other in (("a", "b"), ("b", "a")):
            headers = {"Authorization": f"Bearer {tokens().issue(state[f'user_{actor}'])}"}
            owned = await client.get(path(state, actor, version=version), headers=headers)
            assert owned.status_code == 200
            assert owned.json()["owner_id"] == str(state[f"user_{actor}"])
            # A caller-controlled owner ID cannot override the validated identity.
            denied = await client.get(
                path(state, other, version=version),
                headers=headers,
                params={"owner_id": str(state[f"user_{other}"])},
            )
            missing_path = f"/_test/workflows/{uuid4()}" + (
                f"/versions/{uuid4()}" if version else ""
            )
            missing = await client.get(missing_path, headers=headers)
            assert denied.status_code == missing.status_code == 404
            assert (
                denied.json()["error"]
                == missing.json()["error"]
                == {
                    "code": "NOT_FOUND",
                    "message": "The requested resource does not exist.",
                    "details": None,
                }
            )
            assert denied.json()["request_id"] == denied.headers["x-request-id"]
            assert "private workflow" not in denied.text


async def test_version_must_belong_to_the_specified_owned_workflow(
    repository_database: Database,
    state: dict[str, UUID],
) -> None:
    headers = {"Authorization": f"Bearer {tokens().issue(state['user_a'])}"}
    async with AsyncClient(
        transport=ASGITransport(app=probe_app(repository_database)), base_url="https://test"
    ) as client:
        for workflow_id, version_id in [
            (state["extra_workflow"], state["version_a"]),
            (state["workflow_a"], state["version_b"]),
            (state["workflow_a"], uuid4()),
        ]:
            response = await client.get(
                f"/_test/workflows/{workflow_id}/versions/{version_id}", headers=headers
            )
            assert response.status_code == 404


@pytest.mark.parametrize("version", [False, True])
@pytest.mark.parametrize("credential", ["missing", "invalid", "inactive"])
async def test_authentication_and_current_account_check_precede_ownership_lookup(
    repository_database: Database,
    state: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    version: bool,
    credential: str,
) -> None:
    def should_not_lookup(*args, **kwargs):
        raise AssertionError("Ownership queried before authentication")

    monkeypatch.setattr(WorkflowRepository, "get_owned", should_not_lookup)
    monkeypatch.setattr(WorkflowRepository, "get_version_owned", should_not_lookup)
    headers = {}
    if credential == "invalid":
        headers["Authorization"] = "Bearer private-invalid-access-token"
    elif credential == "inactive":
        headers["Authorization"] = f"Bearer {tokens().issue(state['user_a'])}"
        with repository_database.unit_of_work() as session:
            session.execute(update(User).where(User.id == state["user_a"]).values(is_active=False))
    async with AsyncClient(
        transport=ASGITransport(app=probe_app(repository_database)), base_url="https://test"
    ) as client:
        response = await client.get(path(state, "a", version=version), headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("version", [False, True])
async def test_ownership_storage_error_is_safe_and_recovers(
    repository_database: Database,
    state: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    version: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(*args, **kwargs):
        raise OperationalError(
            "private-ownership-query", {}, RuntimeError("private owner metadata")
        )

    headers = {"Authorization": f"Bearer {tokens().issue(state['user_a'])}"}
    async with AsyncClient(
        transport=ASGITransport(app=probe_app(repository_database)), base_url="https://test"
    ) as client:
        with monkeypatch.context() as patch:
            patch.setattr(WorkflowRepository, "get_version_owned" if version else "get_owned", fail)
            response = await client.get(path(state, "a", version=version), headers=headers)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "private" not in response.text + caplog.text
        assert (
            await client.get(path(state, "a", version=version), headers=headers)
        ).status_code == 200


async def test_owner_id_comes_from_user_and_sql_runs_in_worker_thread(
    repository_database: Database,
    state: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_thread = get_ident()
    original = WorkflowRepository.get_owned
    observed: list[UUID] = []

    def observe(self, *, workflow_id: UUID, owner_id: UUID):
        assert get_ident() != main_thread
        observed.append(owner_id)
        return original(self, workflow_id=workflow_id, owner_id=owner_id)

    monkeypatch.setattr(WorkflowRepository, "get_owned", observe)
    async with AsyncClient(
        transport=ASGITransport(app=probe_app(repository_database)), base_url="https://test"
    ) as client:
        response = await client.get(
            path(state, "a", version=False),
            headers={"Authorization": f"Bearer {tokens().issue(state['user_a'])}"},
            params={"owner_id": str(state["user_b"])},
        )
    assert response.status_code == 200 and observed == [state["user_a"]]
