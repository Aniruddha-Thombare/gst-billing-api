from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest

from app.core.audit_json import REDACTED, to_jsonable


class _Color(str, Enum):
    RED = "red"


def test_decimal_is_exact_string():
    assert to_jsonable(Decimal("1234.50")) == "1234.50"


def test_uuid_date_datetime_enum():
    uid = UUID("12345678-1234-5678-1234-567812345678")
    assert to_jsonable(uid) == str(uid)
    assert to_jsonable(date(2026, 11, 5)) == "2026-11-05"
    assert to_jsonable(datetime(2026, 11, 5, tzinfo=timezone.utc)).startswith("2026-11-05T")
    assert to_jsonable(_Color.RED) == "red"


def test_nested_structures():
    assert to_jsonable({"a": [Decimal("1.00"), {"b": None}]}) == {"a": ["1.00", {"b": None}]}


@pytest.mark.parametrize("key", ["password", "hashed_password", "refresh_token", "api_secret"])
def test_sensitive_keys_redacted(key):
    assert to_jsonable({key: "x"}) == {key: REDACTED}


def test_float_is_rejected():
    with pytest.raises(TypeError):
        to_jsonable({"amount": 1.5})