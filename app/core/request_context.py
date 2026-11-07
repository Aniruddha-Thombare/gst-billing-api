from __future__ import annotations

import ipaddress
from contextvars import ContextVar
from dataclasses import dataclass

_MAX_USER_AGENT_LENGTH = 512


@dataclass(frozen=True)
class RequestContext:
    ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    user_agent: str | None


_EMPTY = RequestContext(ip_address=None, user_agent=None)
_current: ContextVar[RequestContext] = ContextVar("request_context", default=_EMPTY)


def get_request_context() -> RequestContext:
    return _current.get()


def _parse_ip(raw: str | None):
    if not raw:
        return None
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


class RequestContextMiddleware:
    """
    Pure ASGI middleware: stores client IP and user agent for the duration of
    one HTTP request so the audit service can read them without any service
    signature change. The IP is scope["client"]; behind a proxy, run uvicorn
    with --proxy-headers and --forwarded-allow-ips so that value is the real client.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        raw_ip = client[0] if client else None
        user_agent = None
        for name, value in scope.get("headers", []):
            if name == b"user-agent":
                user_agent = value.decode("latin-1")[:_MAX_USER_AGENT_LENGTH]
                break

        token = _current.set(RequestContext(ip_address=_parse_ip(raw_ip), user_agent=user_agent))
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)