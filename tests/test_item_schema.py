from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.item import ItemCreateRequest

_VALID = {"name": "  Widget ", "hsn_sac_code": "8471", "unit": "pcs", "rate": "100.00", "gst_rate": "18"}


def test_valid_item_is_normalised():
    item = ItemCreateRequest(**_VALID)
    assert item.name == "Widget"
    assert item.unit == "PCS"
    assert item.rate == Decimal("100.00")
    assert item.cess_rate == Decimal("0")


@pytest.mark.parametrize("override", [
    {"hsn_sac_code": "AB12"},
    {"hsn_sac_code": "1"},
    {"rate": "-1"},
    {"rate": "10.005"},
    {"gst_rate": "101"},
    {"name": "   "},
])
def test_invalid_items_rejected(override):
    with pytest.raises(ValidationError):
        ItemCreateRequest(**{**_VALID, **override})