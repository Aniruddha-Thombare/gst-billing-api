import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging_config import JsonFormatter, request_id_var
from app.core.request_logging import RequestLoggingMiddleware, unhandled_exception_handler


def _record(message: str = "hello", exc_info=None, **extra) -> logging.LogRecord:
    return logging.getLogger("t").makeRecord(
        "t", logging.INFO, __file__, 1, message, (), exc_info, extra=extra
    )


def test_json_shape_and_extra_fields():
    line = JsonFormatter().format(_record("paid", invoice_id="abc", amount="700.00"))
    data = json.loads(line)
    assert data["message"] == "paid"
    assert data["level"] == "INFO"
    assert data["invoice_id"] == "abc"
    assert data["amount"] == "700.00"
    assert "ts" in data


def test_request_id_comes_from_contextvar():
    token = request_id_var.set("req-12345678")
    try:
        data = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_var.reset(token)
    assert data["request_id"] == "req-12345678"


def test_exception_is_included():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        data = json.loads(JsonFormatter().format(_record(exc_info=sys.exc_info())))
    assert "ValueError: boom" in data["exception"]


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    return app


def test_response_carries_generated_request_id():
    client = TestClient(_build_app())
    response = client.get("/ok")
    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 32


def test_valid_client_request_id_is_echoed_and_bad_one_replaced():
    client = TestClient(_build_app())
    good = client.get("/ok", headers={"X-Request-ID": "client-req-0001"})
    assert good.headers["x-request-id"] == "client-req-0001"
    bad = client.get("/ok", headers={"X-Request-ID": "x y\nz"})
    assert bad.headers["x-request-id"] != "x y\nz"


def test_unhandled_error_returns_generic_body_with_request_id(caplog):
    client = TestClient(_build_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO):
        response = client.get("/boom")
    body = response.json()
    assert response.status_code == 500
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text
    assert body["error"]["request_id"]
    logged = [r for r in caplog.records if r.getMessage() == "unhandled_exception"]
    assert logged and logged[0].exc_info is not None


def test_tenant_and_user_ids_are_logged_when_set():
    from app.core.logging_config import tenant_id_var, user_id_var

    t_token = tenant_id_var.set("tenant-1")
    u_token = user_id_var.set("user-1")
    try:
        data = json.loads(JsonFormatter().format(_record()))
    finally:
        tenant_id_var.reset(t_token)
        user_id_var.reset(u_token)
    assert data["tenant_id"] == "tenant-1"
    assert data["user_id"] == "user-1"


def test_uvicorn_color_message_is_dropped():
    data = json.loads(JsonFormatter().format(_record(color_message="\x1b[36mhi")))
    assert "color_message" not in data