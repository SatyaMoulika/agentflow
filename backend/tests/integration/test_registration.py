"""Registration HTTP/service behavior with real hashing and isolated PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier, get_ident
from uuid import UUID

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.dependencies import get_database_resource
from app.core.security import hash_password
from app.infrastructure.database.models import User
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.exceptions import EmailAlreadyRegisteredError
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import AuthService

pytestmark = pytest.mark.integration
PASSWORD = "  Real registration passphrase  "
PAYLOAD = {"email": "  Moulika@Example.COM  ", "display_name": "  Moulika  ", "password": PASSWORD}


def registration_app(database: Database) -> FastAPI:
    application = create_app()

    async def resource_override() -> Database:
        return database

    # Resource override uses an already-migrated random test schema. HTTP routing,
    # hashing, AuthService, UoW, repository and SQL all execute normally.
    application.dependency_overrides[get_database_resource] = resource_override
    return application


@pytest.mark.anyio
async def test_registration_returns_201_stores_real_hash_and_keeps_credentials_private(
    repository_database: Database,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = registration_app(repository_database)
    main_thread = get_ident()
    hash_threads: list[int] = []
    transaction_threads: list[int] = []

    def observe_hash(password: SecretStr) -> str:
        hash_threads.append(get_ident())
        assert transaction_threads == []  # Hashing must precede the SQL transaction.
        return hash_password(password)

    def observe_begin(connection: Connection) -> None:
        transaction_threads.append(get_ident())

    monkeypatch.setattr("app.modules.auth.service.hash_password", observe_hash)
    event.listen(repository_database.engine, "begin", observe_begin)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/register", json=PAYLOAD)
        assert (await client.get("/api/v1/health")).status_code == 200

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    body = response.json()
    assert set(body) == {"id", "email", "display_name", "is_active", "created_at", "updated_at"}
    assert UUID(body["id"])
    assert body["email"] == "moulika@example.com" and body["display_name"] == "Moulika"
    assert body["is_active"] is True
    assert body["created_at"].endswith("Z") and body["updated_at"].endswith("Z")
    assert len(hash_threads) == 1 and hash_threads[0] != main_thread
    assert transaction_threads == hash_threads
    with repository_database.unit_of_work() as session:
        stored = UserRepository(session).get_by_id(UUID(body["id"]))
        assert stored is not None and stored.email == body["email"]
        assert stored.password_hash.startswith("$argon2id$")
        assert PasswordHasher().verify(stored.password_hash, PASSWORD)
    assert PASSWORD not in response.text + caplog.text
    assert "$argon2id$" not in response.text + caplog.text
    records = [record for record in caplog.records if record.name == "agentflow.http"]
    assert records[0].__dict__["request_id"] == response.headers["x-request-id"]


@pytest.mark.anyio
async def test_normalized_duplicate_returns_safe_409_and_does_not_change_account(
    repository_database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = registration_app(repository_database)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        first = await client.post("/api/v1/auth/register", json=PAYLOAD)
        second = await client.post(
            "/api/v1/auth/register",
            json=PAYLOAD
            | {
                "email": "moulika@example.com",
                "password": "different-private-passphrase",
            },
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {
        "error": {
            "code": "EMAIL_ALREADY_REGISTERED",
            "message": "An account with this email already exists.",
            "details": None,
        },
        "request_id": second.headers["x-request-id"],
    }
    with repository_database.unit_of_work() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        stored = UserRepository(session).get_by_email("moulika@example.com")
        assert stored is not None and PasswordHasher().verify(stored.password_hash, PASSWORD)
    assert PASSWORD not in caplog.text
    assert "different-private-passphrase" not in caplog.text + second.text


@pytest.mark.anyio
async def test_unknown_integrity_error_is_not_misclassified_as_duplicate(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unrelated_failure(self: UserRepository, **kwargs) -> User:
        raise IntegrityError("private-driver-detail", {}, RuntimeError("private-driver-detail"))

    monkeypatch.setattr(UserRepository, "add", unrelated_failure)
    async with AsyncClient(
        transport=ASGITransport(app=registration_app(repository_database)), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/register", json=PAYLOAD)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private-driver-detail" not in response.text


@pytest.mark.anyio
async def test_storage_failure_is_safe_503_and_future_registration_still_works(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = registration_app(repository_database)
    original_add = UserRepository.add

    def unavailable(self: UserRepository, **kwargs) -> User:
        raise OperationalError("private-driver-detail", {}, RuntimeError(PASSWORD))

    monkeypatch.setattr(UserRepository, "add", unavailable)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/register", json=PAYLOAD)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert response.json()["request_id"] == response.headers["x-request-id"]
        monkeypatch.setattr(UserRepository, "add", original_add)
        assert (await client.post("/api/v1/auth/register", json=PAYLOAD)).status_code == 201
    assert PASSWORD not in response.text + caplog.text


def test_registration_response_construction_failure_rolls_back_insert(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_add = UserRepository.add

    def invalid_public_data(self: UserRepository, **kwargs) -> User:
        user = original_add(self, **kwargs)
        # Response validation is inside the transaction, so even a server-side
        # mapping failure after INSERT must not leave a partial registration.
        # A naive timestamp violates the public response's timezone requirement.
        user.created_at = datetime(2026, 10, 30)
        return user

    monkeypatch.setattr(UserRepository, "add", invalid_public_data)

    with pytest.raises(ValidationError):
        AuthService(repository_database).register(RegisterRequest.model_validate(PAYLOAD))
    with repository_database.unit_of_work() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_simultaneous_registrations_map_unique_race_to_one_domain_conflict(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = Barrier(2, timeout=5)
    original_hash = hash_password

    def synchronize_hash(password: SecretStr) -> str:
        result = original_hash(password)
        barrier.wait()  # Both inputs hashed before either transaction begins.
        return result

    monkeypatch.setattr("app.modules.auth.service.hash_password", synchronize_hash)

    def register(email: str) -> str:
        try:
            AuthService(repository_database).register(
                RegisterRequest.model_validate(PAYLOAD | {"email": email})
            )
            return "created"
        except EmailAlreadyRegisteredError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(register, email) for email in ("Race@Example.com", "race@example.com")
        ]
        results = [future.result(timeout=12) for future in futures]
    assert sorted(results) == ["conflict", "created"]
    with repository_database.unit_of_work() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
