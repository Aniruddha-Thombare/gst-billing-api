from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_handlers import http_exception_handler, validation_exception_handler


class _LoginBody(BaseModel):
    email: str
    password: str = Field(min_length=12)


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.get("/protected")
    async def protected():
        raise HTTPException(
            status_code=401,
            detail={"message": "Authorization header missing.", "code": "NO_TOKEN"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.post("/login")
    async def login(body: _LoginBody):
        return {}

    return TestClient(app)


def test_auth_error_uses_error_envelope_and_keeps_header():
    response = _client().get("/protected")
    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "NO_TOKEN", "message": "Authorization header missing."}
    }
    assert response.headers["www-authenticate"] == "Bearer"


def test_unknown_route_uses_error_envelope():
    response = _client().get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_validation_error_shape_and_no_input_echo():
    response = _client().post("/login", json={"email": "a@b.com", "password": "hunter2"})
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"][0]["loc"] == ["body", "password"]
    assert "hunter2" not in response.text