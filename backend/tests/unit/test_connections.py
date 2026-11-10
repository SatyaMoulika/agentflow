"""Credential protection, strict endpoint policy and the actual pinned HTTP transport."""

import json
import socket
from time import monotonic
from uuid import uuid4

import httpcore
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.modules.connections.http_executor import PublicNetworkBackend, get_json
from app.modules.connections.policy import endpoint_url, public_address
from app.modules.connections.schemas import ConnectionCreate
from app.modules.connections.secrets import ConnectionUnavailableError, decrypt, encrypt
from app.modules.connections.service import AuthorizedConnection
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.state import FailureCode
from app.modules.workflows.node_registry import InvalidNodeConfigError, validate_node_config


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost/",
        "https://app.local/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://169.254.169.254/",
        "https://168.63.129.16/",
        "https://user:password@example.com/",
        "https://example.com/?key=private",
        "https://example.com/#fragment",
        "https://example.com:8443/",
        "https://example.com./",
        "https://exam ple.com/",
        "https://example.com/\r\nheader",
        "https://example.com\\@other.com",
        "https://[::ffff:8.8.8.8]/",
        "https://[64:ff9b::7f00:1]/",
        "file:///etc/passwd",
    ],
)
def test_static_endpoint_policy_rejects_unsafe_or_credential_bearing_urls(url: str) -> None:
    with pytest.raises(ValueError) as error:
        endpoint_url(url)
    assert str(error.value).startswith("Use a public HTTPS endpoint")
    assert url not in str(error.value)


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "192.0.2.1",
        "224.0.0.1",
        "0.0.0.0",
        "::",
        "::1",
        "fd00::1",
        "fe80::1",
        "ff02::1",
        "::ffff:8.8.8.8",
        "2002:0808:0808::1",
        "64:ff9b::7f00:1",
        "168.63.129.16",
    ],
)
def test_only_unambiguous_public_addresses_are_allowed(ip: str) -> None:
    assert not public_address(ip)


def test_connection_schema_and_configuration_hide_secrets() -> None:
    data = ConnectionCreate(
        name=" Status ",
        endpoint_url="https://EXAMPLE.com:443",
        auth_type="bearer",
        secret=SecretStr("private-credential"),
    )
    assert data.name == "Status" and data.endpoint_url == "https://example.com/"
    assert "private-credential" not in repr(data)
    for changes in ({"auth_type": "none"}, {"secret": "bad\r\nheader"}, {"secret": None}):
        with pytest.raises(ValidationError):
            ConnectionCreate.model_validate(data.model_dump() | changes)
    with pytest.raises(ValidationError) as error:
        Settings(connection_encryption_key=SecretStr("invalid-private-key"))
    assert "invalid-private-key" not in str(error.value)


def test_cipher_is_randomized_and_bound_to_the_owner_and_connection() -> None:
    key = SecretStr(Fernet.generate_key().decode())
    owner, connection = uuid4(), uuid4()
    secret = SecretStr("private-credential")
    first = encrypt(key, owner, connection, secret)
    assert first != encrypt(key, owner, connection, secret)
    assert secret.get_secret_value() not in first
    assert decrypt(key, owner, connection, first) == secret
    for wrong_owner, wrong_id in ((uuid4(), connection), (owner, uuid4())):
        with pytest.raises(ConnectionUnavailableError):
            decrypt(key, wrong_owner, wrong_id, first)
    for wrong_key in (None, SecretStr(Fernet.generate_key().decode())):
        with pytest.raises(ConnectionUnavailableError):
            decrypt(wrong_key, owner, connection, first)
    with pytest.raises(ConnectionUnavailableError):
        decrypt(key, owner, connection, first[:-4] + "AAAA")


def test_http_config_rejects_embedded_credentials_methods_and_urls() -> None:
    config = {"connection_id": str(uuid4())}
    assert validate_node_config("http", config).model_dump() == config
    for changes in (
        {"url": "https://example.com"},
        {"secret": "private"},
        {"method": "POST"},
        {"connection_id": "not-a-uuid"},
    ):
        with pytest.raises(InvalidNodeConfigError):
            validate_node_config("http", config | changes)


def dns_answers(*addresses: str) -> list[tuple]:
    return [
        (
            socket.AF_INET6 if ":" in ip else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (ip, 443),
        )
        for ip in addresses
    ]


@pytest.mark.parametrize(
    "answers", [[], ["127.0.0.1"], ["8.8.8.8", "10.0.0.1"], ["169.254.169.254"], ["::ffff:8.8.8.8"]]
)
def test_dns_policy_blocks_private_and_mixed_answers_before_opening_a_socket(
    monkeypatch: pytest.MonkeyPatch,
    answers: list[str],
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: dns_answers(*answers))

    def forbidden(*args, **kwargs):
        pytest.fail("A blocked target must not open a socket")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", forbidden)
    with pytest.raises(NodeExecutionError) as error:
        PublicNetworkBackend("api.example.com", monotonic() + 20).connect_tcp(
            "api.example.com", 443
        )
    assert error.value.code == FailureCode.HTTP_TARGET_BLOCKED


def transport(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    *,
    status: int = 200,
    headers: bytes = b"Content-Type: application/json\r\n",
) -> dict:
    recorded: dict = {"dns": [], "tcp": [], "requests": []}
    response = (
        f"HTTP/1.1 {status} Response\r\nContent-Length: {len(body)}\r\n".encode()
        + headers
        + b"\r\n"
        + body
    )

    class Stream(httpcore.MockStream):
        def write(self, buffer, timeout=None):
            recorded["requests"].append(buffer)

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert ssl_context.check_hostname
            recorded["sni"] = server_hostname
            return super().start_tls(ssl_context, server_hostname, timeout)

    def resolve(host, port, **kwargs):
        recorded["dns"].append(host)
        # A second hostname lookup would rebind to a private address.
        return dns_answers("8.8.8.8" if len(recorded["dns"]) == 1 else "127.0.0.1")

    def connect(self, host, port, timeout=None, **kwargs):
        recorded["tcp"].append((host, port))
        return Stream([response])

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    return recorded


def test_actual_http_stack_pins_dns_preserves_tls_hostname_and_sends_only_fixed_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = transport(monkeypatch, b'{"CustomerID":42,"items":[true,null]}')
    output = get_json(
        AuthorizedConnection(
            "https://api.example.com/status", "bearer", SecretStr("private-credential")
        )
    )
    assert output == {"status_code": 200, "body": {"CustomerID": 42, "items": [True, None]}}
    assert record["dns"] == ["api.example.com"] and record["tcp"] == [("8.8.8.8", 443)]
    assert record["sni"] == "api.example.com"
    request = b"".join(record["requests"])
    assert request.startswith(b"GET /status HTTP/1.1")
    assert b"Host: api.example.com" in request
    assert b"Authorization: Bearer private-credential" in request
    assert "private-credential" not in json.dumps(output)


@pytest.mark.parametrize(
    ("body", "status", "headers"),
    [
        (b'{"a":1}', 302, b"Location: https://127.0.0.1/\r\nContent-Type: application/json\r\n"),
        (b'{"a":1}', 500, b"Content-Type: application/json\r\n"),
        (b"not-json", 200, b"Content-Type: application/json\r\n"),
        (b'{"a":1,"a":2}', 200, b"Content-Type: application/json\r\n"),
        (b'{"a":NaN}', 200, b"Content-Type: application/json\r\n"),
        (b'{"a":1}', 200, b"Content-Type: text/html\r\n"),
        (b'{"a":1}', 200, b"Content-Type: application/json\r\nContent-Encoding: gzip\r\n"),
        (b'"' + b"x" * 65537 + b'"', 200, b"Content-Type: application/json\r\n"),
    ],
)
def test_invalid_redirected_oversized_and_compressed_responses_fail_without_retries(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    status: int,
    headers: bytes,
) -> None:
    record = transport(monkeypatch, body, status=status, headers=headers)
    with pytest.raises(NodeExecutionError) as error:
        get_json(AuthorizedConnection("https://api.example.com/", "none"))
    assert error.value.code == FailureCode.HTTP_REQUEST_FAILED
    assert len(record["tcp"]) == 1


def test_escaped_credentials_echoed_in_a_response_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = 'private-"credential'
    transport(monkeypatch, json.dumps({"headers": {"key": secret}}).encode())
    with pytest.raises(NodeExecutionError):
        get_json(AuthorizedConnection("https://api.example.com/", "api_key", SecretStr(secret)))


def test_timeouts_are_static_and_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise httpcore.ConnectTimeout("private-network-details")

    monkeypatch.setattr(PublicNetworkBackend, "connect_tcp", timeout)
    with pytest.raises(NodeExecutionError) as error:
        get_json(AuthorizedConnection("https://api.example.com/", "none"))
    assert error.value.code == FailureCode.DEADLINE_EXCEEDED and calls == [1]
    assert "private-network-details" not in str(error.value)
