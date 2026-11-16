"""Bounded Gmail OAuth and read primitives; callers manage ownership and transactions.

These functions do not persist credentials, define API routes, or trigger workflows.
They never log response bodies, authorization codes, tokens or message content.
"""

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MAX_RESPONSE_BYTES = 262144
MAX_TEXT_BYTES = 16384
_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class GmailProviderError(Exception):
    """Static errors prevent upstream data and credentials from reaching callers."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("The Gmail operation could not be completed.")


@dataclass(frozen=True)
class OAuthToken:
    access_token: SecretStr = field(repr=False)
    refresh_token: SecretStr | None = field(default=None, repr=False)
    expires_in: int = 0


def oauth_parameters() -> tuple[str, SecretStr, str]:
    """Create an opaque state and PKCE verifier/challenge for one authorization attempt."""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return state, SecretStr(verifier), challenge


def authorization_url(*, client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """Request only read access; identity/state binding must be enforced by the caller."""
    if (
        not client_id
        or not redirect_uri
        or not _ID.fullmatch(state)
        or not _ID.fullmatch(challenge)
    ):
        raise GmailProviderError("CONFIGURATION_INVALID")
    return (
        AUTHORIZATION_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": READ_SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError()
        value[key] = item
    return value


def _request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    """One bounded request to code-owned Google endpoints; never follow redirects or retry."""
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), trust_env=False) as client:
            headers = dict(kwargs.pop("headers", {}))
            headers["Accept-Encoding"] = "identity"
            kwargs["headers"] = headers
            with client.stream(method, url, follow_redirects=False, **kwargs) as response:
                if response.status_code in (401, 403):
                    raise GmailProviderError("AUTHORIZATION_FAILED")
                if response.status_code == 429:
                    raise GmailProviderError("RATE_LIMITED")
                if response.status_code != 200:
                    raise GmailProviderError("PROVIDER_UNAVAILABLE")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise GmailProviderError("INVALID_RESPONSE")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise GmailProviderError("RESPONSE_TOO_LARGE")
                    body.extend(chunk)
        payload = json.loads(bytes(body), object_pairs_hook=_unique)
        if not isinstance(payload, dict):
            raise ValueError()
        return payload
    except GmailProviderError:
        raise
    except (httpx.HTTPError, OSError, ValueError, TypeError, RecursionError):
        raise GmailProviderError("PROVIDER_UNAVAILABLE") from None


def exchange_code(
    *,
    client_id: str,
    client_secret: SecretStr,
    redirect_uri: str,
    code: SecretStr,
    verifier: SecretStr,
) -> OAuthToken:
    response = _request(
        "POST",
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret.get_secret_value(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code": code.get_secret_value(),
            "code_verifier": verifier.get_secret_value(),
        },
    )
    scopes = response.get("scope")
    if not isinstance(scopes, str) or READ_SCOPE not in scopes.split():
        raise GmailProviderError("AUTHORIZATION_FAILED")
    return _token(response)


def refresh_access_token(
    *, client_id: str, client_secret: SecretStr, refresh_token: SecretStr
) -> OAuthToken:
    response = _request(
        "POST",
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret.get_secret_value(),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token.get_secret_value(),
        },
    )
    return _token(response)


def _token(response: dict[str, Any]) -> OAuthToken:
    access = response.get("access_token")
    refresh = response.get("refresh_token")
    expires = response.get("expires_in")
    scopes = response.get("scope")
    token_type = response.get("token_type")
    if (
        not isinstance(access, str)
        or not 1 <= len(access) <= 4096
        or (refresh is not None and (not isinstance(refresh, str) or not 1 <= len(refresh) <= 4096))
        or type(expires) is not int
        or not 1 <= expires <= 86400
        or not isinstance(token_type, str)
        or token_type.lower() != "bearer"
        or (
            scopes is not None and (not isinstance(scopes, str) or READ_SCOPE not in scopes.split())
        )
    ):
        raise GmailProviderError("INVALID_TOKEN_RESPONSE")
    return OAuthToken(
        SecretStr(access), SecretStr(refresh) if refresh is not None else None, expires
    )


def list_message_ids(access_token: SecretStr, *, limit: int = 10) -> list[str]:
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Invalid message limit")
    result = _request(
        "GET",
        GMAIL_API + "/messages",
        params={"maxResults": limit, "labelIds": "INBOX"},
        headers={"Authorization": "Bearer " + access_token.get_secret_value()},
    )
    messages = result.get("messages", [])
    if not isinstance(messages, list) or len(messages) > limit:
        raise GmailProviderError("INVALID_RESPONSE")
    identities = []
    for item in messages:
        identity = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            raise GmailProviderError("INVALID_RESPONSE")
        identities.append(identity)
    return identities


def validate_message_id(message_id: str) -> None:
    if not isinstance(message_id, str) or not _ID.fullmatch(message_id):
        raise ValueError("Invalid message identifier")


def read_message(access_token: SecretStr, message_id: str) -> dict[str, Any]:
    validate_message_id(message_id)
    return _request(
        "GET",
        GMAIL_API + "/messages/" + message_id,
        params={"format": "full"},
        headers={"Authorization": "Bearer " + access_token.get_secret_value()},
    )


def plain_text_message(message: dict[str, Any]) -> str:
    """Extract bounded plain text without loading attachments or interpreting HTML."""
    root = message.get("payload")
    if not isinstance(root, dict):
        raise GmailProviderError("INVALID_RESPONSE")
    pending: list[tuple[dict[str, Any], int]] = [(root, 0)]
    parts: list[str] = []
    size = 0
    seen = 0
    while pending:
        part, depth = pending.pop()
        seen += 1
        if seen > 100 or depth > 16:
            raise GmailProviderError("RESPONSE_TOO_LARGE")
        children = part.get("parts", [])
        if not isinstance(children, list) or any(not isinstance(item, dict) for item in children):
            raise GmailProviderError("INVALID_RESPONSE")
        pending.extend((item, depth + 1) for item in reversed(children))
        if part.get("mimeType") != "text/plain" or part.get("filename"):
            continue
        body = part.get("body")
        if not isinstance(body, dict):
            raise GmailProviderError("INVALID_RESPONSE")
        data = body.get("data", "")
        if not isinstance(data, str) or len(data) > (MAX_TEXT_BYTES * 2):
            raise GmailProviderError("RESPONSE_TOO_LARGE")
        try:
            raw = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
            value = raw.decode("utf-8")
        except (ValueError, UnicodeError):
            raise GmailProviderError("INVALID_RESPONSE") from None
        size += len(raw)
        if size > MAX_TEXT_BYTES:
            raise GmailProviderError("RESPONSE_TOO_LARGE")
        parts.append(value)
    return "\n".join(parts)
