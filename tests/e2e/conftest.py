"""
End-to-end fixtures. These tests are BLACK-BOX: they talk HTTP to the test API
(default http://localhost:8001, database gst_test) and never import app code.

Start the stack first:  bash scripts/reset_test_db.sh
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from dotenv import dotenv_values

DEFAULT_API_URL = "http://localhost:8001"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: black-box test against the running test API")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/e2e" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)
            if item.get_closest_marker("asyncio") is None and _is_coroutine(item):
                item.add_marker(pytest.mark.asyncio)


def _is_coroutine(item: pytest.Item) -> bool:
    import inspect

    func = getattr(item, "obj", None)
    return inspect.iscoroutinefunction(func)


@pytest.fixture(scope="session")
def api_url() -> str:
    url = os.getenv("E2E_API_URL", DEFAULT_API_URL).rstrip("/")
    if url.endswith(":8000"):
        pytest.exit("Refusing to run e2e tests against :8000 (the DEV database). Use :8001.", 2)
    try:
        response = httpx.get(f"{url}/health", timeout=3)
    except httpx.HTTPError:
        pytest.skip(f"Test API not reachable at {url}. Run: bash scripts/reset_test_db.sh")
    if response.status_code != 200:
        pytest.skip(f"Test API at {url} is unhealthy ({response.status_code}).")
    return url


@pytest_asyncio.fixture
async def client(api_url: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=api_url,
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=50),
    ) as http_client:
        yield http_client


def _db_settings() -> dict[str, object]:
    file_values = dotenv_values(Path(".env"))

    def pick(key: str, default: str | None = None) -> str | None:
        return os.getenv(key) or file_values.get(key) or default

    return {
        "host": os.getenv("E2E_DB_HOST", "localhost"),
        "port": int(os.getenv("E2E_DB_PORT", "5433")),
        "user": pick("POSTGRES_USER", "postgres"),
        "password": pick("POSTGRES_PASSWORD"),
        "database": "gst_test",  # hard-coded on purpose: never the dev database
    }


@pytest_asyncio.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    try:
        connection = await asyncpg.connect(**_db_settings())
    except (OSError, asyncpg.PostgresError) as error:
        pytest.skip(f"Cannot reach gst_test on localhost:5433 ({error!r})")
    try:
        yield connection
    finally:
        await connection.close()
