"""Google API boundary tests use synthetic data and never contact a real account."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from app.modules.gmail import provider


def transport(monkeypatch, handler):
    calls = []
    original = httpx.Client

    def handle(request):
        calls.append(request)
        return handler(request)

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(provider.httpx, "Client", client)
    return calls


def test_authorization_url_uses_fresh_state_pkce_and_read_only_scope():
    state, verifier, challenge = provider.oauth_parameters()
    other_state, other_verifier, _ = provider.oauth_parameters()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.get_secret_value().encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert state != other_state and verifier != other_verifier and challenge == expected
    url = provider.authorization_url(
        client_id="synthetic-client",
        redirect_uri="http://localhost/callback",
        state=state,
        challenge=challenge,
    )
    parsed = urlsplit(url)
    values = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.netloc == "accounts.google.com"
    assert values["scope"] == [provider.READ_SCOPE]
    assert values["state"] == [state] and values["code_challenge"] == [challenge]
    assert values["code_challenge_method"] == ["S256"]
    assert verifier.get_secret_value() not in url


def test_exchange_code_and_refresh_keep_secrets_out_of_repr(monkeypatch):
    calls = transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "access_token": "private-access",
                "refresh_token": "private-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": provider.READ_SCOPE,
            },
        ),
    )
    token = provider.exchange_code(
        client_id="synthetic-client",
        client_secret=SecretStr("private-client-secret"),
        redirect_uri="http://localhost/callback",
        code=SecretStr("private-code"),
        verifier=SecretStr("private-verifier"),
    )
    assert token.expires_in == 3600 and token.refresh_token is not None
    assert "private" not in repr(token)
    refreshed = provider.refresh_access_token(
        client_id="synthetic-client",
        client_secret=SecretStr("private-client-secret"),
        refresh_token=token.refresh_token,
    )
    assert refreshed.access_token.get_secret_value() == "private-access"
    assert len(calls) == 2 and all(str(call.url) == provider.TOKEN_URL for call in calls)


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "x", "expires_in": True, "token_type": "Bearer"},
        {"access_token": "x", "expires_in": 3600, "token_type": None},
        {"access_token": "x", "expires_in": 3600, "token_type": "Bearer", "scope": "wrong"},
    ],
)
def test_invalid_token_response_fails_closed(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(provider.GmailProviderError) as error:
        provider.refresh_access_token(
            client_id="client",
            client_secret=SecretStr("secret"),
            refresh_token=SecretStr("refresh"),
        )
    assert error.value.code == "INVALID_TOKEN_RESPONSE"
    assert "secret" not in str(error.value)


def test_list_and_get_use_fixed_google_endpoints(monkeypatch):
    def handle(request):
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "abc123"}]})
        return httpx.Response(200, json={"id": "abc123", "payload": {}})

    calls = transport(monkeypatch, handle)
    token = SecretStr("private-access")
    assert provider.list_message_ids(token) == ["abc123"]
    assert provider.read_message(token, "abc123")["id"] == "abc123"
    assert len(calls) == 2 and all(call.url.host == "gmail.googleapis.com" for call in calls)
    with pytest.raises(ValueError):
        provider.read_message(token, "../../other")
    assert len(calls) == 2


def test_extract_plain_text_ignores_html_and_attachments():
    data = base64.urlsafe_b64encode(b"synthetic message").decode().rstrip("=")
    message = {
        "payload": {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": data}},
                {"mimeType": "text/html", "body": {"data": "ignored"}},
                {"mimeType": "text/plain", "filename": "file.txt", "body": {"data": "ignored"}},
            ],
        }
    }
    assert provider.plain_text_message(message) == "synthetic message"


def test_extract_plain_text_rejects_malformed_and_oversized_content():
    malformed = {"payload": {"mimeType": "text/plain", "body": {"data": "!"}}}
    with pytest.raises(provider.GmailProviderError):
        provider.plain_text_message(malformed)
    data = base64.urlsafe_b64encode(b"x" * (provider.MAX_TEXT_BYTES + 1)).decode()
    oversized = {"payload": {"mimeType": "text/plain", "body": {"data": data}}}
    with pytest.raises(provider.GmailProviderError) as error:
        provider.plain_text_message(oversized)
    assert error.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": "private upstream detail"}),
        httpx.Response(200, content=b'{"id":"a","id":"b"}'),
        httpx.Response(200, content=b"x" * (provider.MAX_RESPONSE_BYTES + 1)),
        httpx.Response(200, content=b"compressed", headers={"Content-Encoding": "br"}),
    ],
)
def test_provider_errors_never_expose_response_or_token(monkeypatch, response):
    calls = transport(monkeypatch, lambda request: response)
    with pytest.raises(provider.GmailProviderError) as error:
        provider.read_message(SecretStr("private-access"), "abc123")
    assert len(calls) == 1
    assert "private" not in str(error.value) and "private" not in json.dumps(error.value.args)
