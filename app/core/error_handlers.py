"""Normalises every non-business error into {"error": {"code", "message"}}."""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_DEFAULT_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    429: "TOO_MANY_REQUESTS",
}


def _error_body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, **extra}}


async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Covers our auth HTTPExceptions (dict detail) and Starlette's 404/405 (str detail)."""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        code, message = str(detail["code"]), str(detail["message"])
    else:
        code = _DEFAULT_CODES.get(exc.status_code, "HTTP_ERROR")
        message = detail if isinstance(detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(code, message),
        headers=exc.headers,  # keeps WWW-Authenticate on 401s
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 with field-level problems. Never echoes the submitted values."""
    details = [
        {
            "loc": [str(part) for part in error["loc"]],
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_body("VALIDATION_ERROR", "Request validation failed.", details=details),
    )