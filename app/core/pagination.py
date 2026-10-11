import base64
import json
from datetime import date
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.core.exceptions import InvalidListQueryError

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of results. next_cursor is None on the last page."""
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(sort_value: str, row_id: UUID) -> str:
    """Opaque cursor for keyset pagination: the last row's sort value and id."""
    raw = json.dumps({"v": sort_value, "i": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> tuple[str, UUID] | None:
    """Returns (sort_value, row_id), or None when no cursor was given. Bad input -> 422."""
    if cursor is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return str(data["v"]), UUID(data["i"])
    except (ValueError, KeyError, TypeError):
        raise InvalidListQueryError("Invalid cursor.")


def decode_date_cursor(cursor: str | None) -> tuple[date, UUID] | None:
    """Like decode_cursor, for lists sorted by a date column."""
    decoded = decode_cursor(cursor)
    if decoded is None:
        return None
    try:
        return date.fromisoformat(decoded[0]), decoded[1]
    except ValueError:
        raise InvalidListQueryError("Invalid cursor.")