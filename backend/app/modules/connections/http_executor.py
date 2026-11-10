"""One bounded GET to an authorized endpoint, with public DNS pinned at connect."""

import json
import socket
import ssl
from collections.abc import Iterable
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpcore

from app.modules.connections.policy import endpoint_url, public_address
from app.modules.connections.service import AuthorizedConnection
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.payloads import InvalidExecutionPayloadError, copy_payload
from app.modules.executions.state import FailureCode

MAX_RESPONSE_BYTES = 65536
OPERATION_SECONDS = 20


def _target_blocked() -> NodeExecutionError:
    return NodeExecutionError(FailureCode.HTTP_TARGET_BLOCKED)


class _DeadlineStream(httpcore.NetworkStream):
    def __init__(self, stream: httpcore.NetworkStream, deadline: float) -> None:
        self.stream = stream
        self.deadline = deadline

    def _timeout(self, timeout: float | None) -> float:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise httpcore.ReadTimeout()
        return min(timeout if timeout is not None else 5, remaining)

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self.stream.read(max_bytes, timeout=self._timeout(timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.stream.write(buffer, timeout=self._timeout(timeout))

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        return _DeadlineStream(
            self.stream.start_tls(ssl_context, server_hostname, self._timeout(timeout)),
            self.deadline,
        )

    def close(self) -> None:
        self.stream.close()

    def get_extra_info(self, info: str) -> Any:
        return self.stream.get_extra_info(info)


class PublicNetworkBackend(httpcore.NetworkBackend):
    def __init__(self, host: str, deadline: float) -> None:
        self.host = host
        self.deadline = deadline

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        if host != self.host or port != 443 or local_address is not None:
            raise _target_blocked()
        # Every DNS answer must be public. The socket receives a numeric address,
        # never the hostname again; HTTP Host and TLS certificate/SNI keep the hostname.
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(str(answer[4][0]) for answer in answers))
        if not addresses or len(addresses) > 16 or any(not public_address(ip) for ip in addresses):
            raise _target_blocked()
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise httpcore.ConnectTimeout()
        stream = httpcore.SyncBackend().connect_tcp(
            addresses[0], port, min(timeout or 5, remaining), socket_options=socket_options
        )
        return _DeadlineStream(stream, self.deadline)

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        raise _target_blocked()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def get_json(connection: AuthorizedConnection) -> dict[str, Any]:
    """Do not send workflow input, follow redirects, use proxies, or retry requests."""
    try:
        url = endpoint_url(connection.endpoint_url)
    except ValueError:
        raise _target_blocked() from None
    secret = connection.secret.get_secret_value() if connection.secret is not None else None
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    if connection.auth_type == "bearer" and secret:
        headers["Authorization"] = f"Bearer {secret}"
    elif connection.auth_type == "api_key" and secret:
        headers["X-API-Key"] = secret
    elif connection.auth_type != "none":
        raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE)
    try:
        deadline = monotonic() + OPERATION_SECONDS
        host = urlsplit(url).hostname
        assert host is not None
        # A fresh direct pool per call cannot reuse another endpoint's connection.
        with (
            httpcore.ConnectionPool(
                network_backend=PublicNetworkBackend(host, deadline),
                max_connections=1,
                max_keepalive_connections=0,
                retries=0,
            ) as pool,
            pool.stream(
                "GET",
                url,
                headers=list(headers.items()),
                extensions={"timeout": {"connect": 5, "read": 5, "write": 5, "pool": 5}},
            ) as response,
        ):
            if not 200 <= response.status < 300:
                raise ValueError()
            response_headers = {key.lower(): value.lower() for key, value in response.headers}
            content_type = response_headers.get(b"content-type", b"").split(b";", 1)[0].strip()
            if (
                not (content_type == b"application/json" or content_type.endswith(b"+json"))
                or response_headers.get(b"content-encoding", b"identity") != b"identity"
            ):
                raise ValueError()
            body = bytearray()
            for chunk in response.iter_stream():
                if monotonic() >= deadline or len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError()
                body.extend(chunk)
            decoded = json.loads(bytes(body).decode("utf-8"), object_pairs_hook=_unique_object)
            output = copy_payload({"status_code": response.status, "body": decoded})
            # A service may echo request headers. Never persist the usable credential.
            if secret is not None:
                pending: list[Any] = [output]
                while pending:
                    item = pending.pop()
                    if isinstance(item, str) and secret in item:
                        raise ValueError()
                    if isinstance(item, dict):
                        pending.extend(item.keys())
                        pending.extend(item.values())
                    elif isinstance(item, list):
                        pending.extend(item)
            return output
    except (httpcore.TimeoutException, TimeoutError):
        raise NodeExecutionError(FailureCode.DEADLINE_EXCEEDED) from None
    except (
        httpcore.NetworkError,
        httpcore.ProtocolError,
        OSError,
        ValueError,
        UnicodeError,
        RecursionError,
        InvalidExecutionPayloadError,
    ):
        raise NodeExecutionError(FailureCode.HTTP_REQUEST_FAILED) from None
