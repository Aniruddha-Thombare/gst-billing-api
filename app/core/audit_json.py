from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

REDACTED = "***REDACTED***"
_SENSITIVE_FRAGMENTS = ("password", "token", "secret")


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def to_jsonable(value: Any) -> Any:
    """
    Pure converter: makes any audit payload JSONB-safe.
    Decimal -> exact string (never float), UUID/date/datetime -> str,
    Enum -> its value, sensitive dict keys -> redacted.
    A float is a programming error in a financial system and raises.
    """
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed in an audit payload; use Decimal")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if _is_sensitive(str(key)) else to_jsonable(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return str(value)