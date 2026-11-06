"""Host-only refresh/CSRF cookie delivery; raw refresh credentials stay out of JSON."""

from datetime import UTC, datetime

from starlette.responses import Response

from app.modules.auth.service import AuthResult


def cookie_names(secure: bool) -> tuple[str, str]:
    prefix = "__Host-" if secure else ""
    return f"{prefix}agentflow_refresh", f"{prefix}agentflow_csrf"


def set_auth_cookies(response: Response, result: AuthResult, *, secure: bool) -> None:
    refresh_name, csrf_name = cookie_names(secure)
    # PostgreSQL may return ZoneInfo("Etc/UTC"); cookie GMT formatting requires UTC.
    expires_at = result.expires_at.astimezone(UTC)
    max_age = max(0, int((expires_at - datetime.now(UTC)).total_seconds()))
    for name, value, http_only in (
        (refresh_name, result.credentials.refresh_token, True),
        (csrf_name, result.credentials.csrf_token, False),
    ):
        response.set_cookie(
            name,
            value.get_secret_value(),
            max_age=max_age,
            expires=expires_at,
            path="/",
            secure=secure,
            httponly=http_only,
            samesite="strict",
        )


def clear_auth_cookies(response: Response, *, secure: bool) -> None:
    refresh_name, csrf_name = cookie_names(secure)
    for name, http_only in ((refresh_name, True), (csrf_name, False)):
        response.delete_cookie(name, path="/", secure=secure, httponly=http_only, samesite="strict")
