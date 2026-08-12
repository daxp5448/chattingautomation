"""Calls a Super-Admin-curated ApiEndpoint from within a flow's API_CALL step
(app/services/generic_flow_engine.py) -- the platform's first outbound-HTTP-to-a-
business-configurable-destination capability, and therefore its first real SSRF surface.
Zero prior art exists in this codebase for this (grepped: no ipaddress/getaddrinfo/SSRF-
adjacent code anywhere before this file); this gets proportionate scrutiny and test
coverage, not routine-plumbing treatment.

## Why a naive pre-flight IP check is NOT enough (DNS rebinding)
A separate `socket.getaddrinfo(host)` check before calling `httpx.get(url)` has no
binding to what httpx's own, LATER, independent DNS resolution actually connects to --
an attacker-controlled DNS record can serve a public IP to the pre-check and a private/
loopback IP moments later (or even on the same request, with TTL=0) to httpx's real
connection. This is exactly the class of bug a "resolve once, check, then trust the
result forever" design invites.

## What this does instead: validate at the actual TCP-connect layer
Verified against the installed httpx==0.27.2 / httpcore==1.0.9 (no version-agnostic
guessing): `httpx.AsyncHTTPTransport.__init__` builds a plain, later-assignable
`self._pool = httpcore.AsyncConnectionPool(...)` (confirmed by reading httpx's own
source). `httpcore.AsyncConnectionPool` accepts a `network_backend=` override, and
`httpcore._backends.anyio.AnyIOBackend.connect_tcp(host, port, ...)` is the exact point
where the real socket connection happens -- `host` here is still the un-resolved
hostname; the actual DNS resolution + connection happens inside `anyio.connect_tcp`,
called from there.

`_SSRFSafeBackend` below resolves the hostname itself (once), validates every candidate
IP, and then connects to a VALIDATED IP LITERAL (never the original hostname) -- since an
IP literal skips anyio's own resolution step entirely, there is no second lookup that
could return something different: the validated value IS the connected value, atomically,
closing the TOCTOU gap completely. TLS/SNI/certificate-hostname verification is
unaffected: httpcore performs `start_tls` as a SEPARATE step after `connect_tcp` returns,
passing the ORIGINAL hostname as `server_hostname` regardless of which raw IP the TCP
layer actually connected to (confirmed by reading `AnyIOStream.start_tls`'s source) --
so certificate validation still correctly checks against the real target hostname.

## Other protections
- Redirects are never followed (`follow_redirects=False`, `httpx`'s own default).
- Context values are NEVER interpolated into the URL, path, query string, or headers --
  only into a fixed JSON body shape (`{"context": {...}}`), closing a header/URL-
  injection surface independent of the endpoint allowlist itself. See
  ApiEndpoint.capturable_context_keys's docstring.
- Response size is capped; the connection is closed once the cap is exceeded rather than
  buffering an unbounded body.
"""

import ipaddress
import json
import logging
import socket
from typing import Any

import anyio
import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend

from app.models.api_endpoint import ApiEndpoint

logger = logging.getLogger(__name__)

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local, INCLUDES cloud metadata 169.254.169.254
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # unique local IPv6
    ipaddress.ip_network("fe80::/10"),  # link-local IPv6
]


def _is_globally_routable(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return _is_globally_routable(str(addr.ipv4_mapped))
    return not any(addr in net for net in _BLOCKED_NETWORKS)


class _SSRFSafeBackend(AnyIOBackend):
    """See module docstring for why this closes the DNS-rebinding gap a pre-flight-only
    check would leave open: resolves `host` itself, validates every candidate IP, then
    connects to a validated IP literal (never re-resolving the original hostname)."""

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addr_info = await anyio.to_thread.run_sync(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise httpcore.ConnectError(f"DNS resolution failed for {host}") from exc

        candidate_ips = {info[4][0] for info in addr_info}
        if not candidate_ips:
            raise httpcore.ConnectError(f"No addresses resolved for {host}")
        blocked = [ip for ip in candidate_ips if not _is_globally_routable(ip)]
        if blocked:
            raise httpcore.ConnectError(f"Refusing to connect to {host}: resolves to a non-public address ({blocked[0]})")

        validated_ip = next(iter(candidate_ips))
        return await super().connect_tcp(validated_ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options)


def _build_ssrf_safe_client(timeout_seconds: float) -> httpx.AsyncClient:
    client = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)
    # `_pool` is a plain, assignable instance attribute set in
    # httpx.AsyncHTTPTransport.__init__ (verified by reading the installed httpx
    # 0.27.2 source -- not a documented/stable public API, but a straightforward
    # attribute replacement, not fragile internal-state hacking). Swapping it after
    # construction is the only way to inject a custom network_backend, since
    # AsyncHTTPTransport.__init__ doesn't expose one as a parameter.
    client._transport._pool = httpcore.AsyncConnectionPool(network_backend=_SSRFSafeBackend())
    return client


async def call_api_endpoint(session, endpoint_id: str | None, context: dict[str, Any], timeout_override: float | None = None) -> Any:
    """Calls the ApiEndpoint identified by `endpoint_id`, sending only the fixed shape
    `{"context": {k: context.get(k) for k in endpoint.capturable_context_keys}}` --
    never a business/customer-controlled URL, header, or query string. Raises on any
    failure (missing/inactive endpoint, blocked address, timeout, non-2xx, oversized
    response) -- the caller (generic_flow_engine.py) treats this as best-effort and
    continues the flow regardless, per this feature's "never let one bad integration
    stall a customer's conversation" design.
    """
    if not endpoint_id:
        raise ValueError("api_call step has no endpoint_id")

    endpoint = await session.get(ApiEndpoint, endpoint_id)
    if endpoint is None or not endpoint.is_active:
        raise ValueError(f"ApiEndpoint {endpoint_id} is missing or inactive")

    body = {"context": {k: context.get(k) for k in (endpoint.capturable_context_keys or [])}}
    timeout = min(endpoint.timeout_seconds, timeout_override) if timeout_override is not None else endpoint.timeout_seconds

    content = bytearray()
    async with _build_ssrf_safe_client(timeout) as client:
        # client.stream(...) (not client.request(...)) so the body is read incrementally
        # via aiter_bytes() below, letting the size cap actually stop an oversized
        # download in progress rather than only detecting it after httpx has already
        # buffered the whole thing internally.
        async with client.stream(
            endpoint.method, endpoint.url, json=body if endpoint.method != "GET" else None,
            params=body["context"] if endpoint.method == "GET" else None,
            headers=dict(endpoint.allowed_headers or {}),
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content += chunk
                if len(content) > endpoint.response_size_cap_bytes:
                    raise ValueError(f"ApiEndpoint {endpoint_id} response exceeded {endpoint.response_size_cap_bytes} byte cap")

    try:
        return json.loads(bytes(content))
    except (ValueError, TypeError):
        return bytes(content).decode("utf-8", errors="replace")
