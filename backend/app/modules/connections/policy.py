"""Static endpoint policy; DNS is checked again at the actual socket boundary."""

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit


def public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped or address.sixtofour or address.teredo:
            return False
        if address in ipaddress.ip_network("64:ff9b::/96"):
            return False
    # Azure's virtual platform endpoint is globally numbered but internal.
    return value != "168.63.129.16"


def endpoint_url(value: str) -> str:
    """Allow one exact HTTPS endpoint, without embedded credentials or query secrets."""
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (
            not value.isascii()
            or len(value) > 1000
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or "\\" in value
            or parts.scheme != "https"
            or parts.port not in {None, 443}
            or parts.username is not None
            or parts.password is not None
            or "?" in value
            or "#" in value
            or not host
            or "%" in host
            or host.endswith(".")
        ):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if (
                "." not in host
                or len(host) > 253
                or any(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                    for label in host.split(".")
                )
                or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
            ):
                raise ValueError() from None
        else:
            if not public_address(host):
                raise ValueError()
        authority = f"[{host}]" if ":" in host else host
        return urlunsplit(("https", authority, parts.path or "/", "", ""))
    except ValueError:
        raise ValueError(
            "Use a public HTTPS endpoint on port 443 without credentials or query."
        ) from None
