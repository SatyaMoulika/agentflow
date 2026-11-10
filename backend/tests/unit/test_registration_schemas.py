"""Registration validation/normalization without exposing credential inputs."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import RegisterRequest, UserResponse

PASSWORD = "  Example private passphrase  "


def test_normalizes_public_fields_and_preserves_password_exactly() -> None:
    data = RegisterRequest.model_validate(
        {
            "email": "  Owner@Example.COM ",
            "display_name": "  Moulika  ",
            "password": PASSWORD,
        }
    )
    assert data.email == "owner@example.com"
    assert data.display_name == "Moulika"
    assert data.password.get_secret_value() == PASSWORD
    assert PASSWORD not in repr(data)
    assert PASSWORD not in data.model_dump_json()


@pytest.mark.parametrize("password", ["x" * 8, "x" * 128, "界" * 8])
def test_accepts_password_length_boundaries_and_unicode(password: str) -> None:
    data = RegisterRequest.model_validate(
        {
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": password,
        }
    )
    assert data.password.get_secret_value() == password


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "invalid-private-email"},
        {"email": 123},
        {"password": "private"},
        {"password": "p" * 129},
        {"password": " " * 8},
        {"password": 123456789012345},
        {"display_name": "  "},
        {"display_name": "n" * 101},
        {"display_name": 123},
        {"is_active": False},
        {"password_hash": "injected"},
    ],
)
def test_rejects_invalid_input_and_privilege_fields_without_echoing_password(
    overrides: dict,
) -> None:
    with pytest.raises(ValidationError) as error:
        RegisterRequest.model_validate(
            {
                "email": "owner@example.com",
                "display_name": "Owner",
                "password": PASSWORD,
            }
            | overrides
        )
    assert PASSWORD not in str(error.value)
    assert "private" not in str(error.value)


def test_public_response_omits_storage_secrets_and_normalizes_utc() -> None:
    timestamp = datetime(2026, 10, 30, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    response = UserResponse.model_validate(
        {
            "id": uuid4(),
            "email": "owner@example.com",
            "display_name": "Owner",
            "is_active": True,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )
    assert response.created_at.tzinfo == UTC
    assert response.model_dump(mode="json")["created_at"].endswith("Z")
    assert set(response.model_dump()) == {
        "id",
        "email",
        "display_name",
        "is_active",
        "created_at",
        "updated_at",
    }
