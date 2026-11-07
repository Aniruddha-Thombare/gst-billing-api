"""Request-ID + access-log middleware and the catch-all 500 handler."""

import logging
import re
import time
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging_config import request_id_var

access_logger = logging.getLogger("app.request")
error_logger = logging.getLogger("app.errors")

_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
_HEALTH_PREFIX = "/health"


def resolve_request_id(scope: Scope) -> str:
    """Accept a client X-Request-ID only if it is a safe token (no log injection)."""
    supplied = Headers(scope=scope).get("x-request-id")
    if supplied and _VALID_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid4().hex


class RequestLoggingMiddleware:
    """Pure ASGI. Sets request_id, echoes it as a header, logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(scope)
        scope["request_id"] = request_id  # readable by the 500 handler
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500  # stays 500 if the app raises before responding

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            self._log_access(scope, status_code, started)
            request_id_var.reset(token)

    @staticmethod
    def _log_access(scope: Scope, status_code: int, started: float) -> None:
        path = scope["path"]
        if path.startswith(_HEALTH_PREFIX) and status_code < 400:
            return  # docker/ALB health probes would drown the logs
        level = logging.INFO if status_code < 400 else logging.WARNING
        access_logger.log(
            level,
            "request",
            extra={
                "method": scope["method"],
                "path": path,  # no query string: cursors/filters stay out of logs
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Full traceback to logs/Sentry; generic body + request_id to the client."""
    request_id = request.scope.get("request_id")
    error_logger.error(
        "unhandled_exception",
        exc_info=exc,
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            }
        },
    )