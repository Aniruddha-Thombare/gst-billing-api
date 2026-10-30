import pytest

from app.domain.gstr1_rules import OutwardSection
from app.domain.gstr3b_rules import Gstr3bBucket, belongs_in_table_3_2, gstr3b_bucket


@pytest.mark.parametrize(
    "section, supply_type, expected",
    [
        (OutwardSection.B2B, "intrastate", Gstr3bBucket.TAXABLE),
        (OutwardSection.B2CS, "interstate", Gstr3bBucket.TAXABLE),
        (OutwardSection.B2CL, "interstate", Gstr3bBucket.TAXABLE),
        (OutwardSection.CDNR, "intrastate", Gstr3bBucket.TAXABLE),
        (OutwardSection.EXPORT, "export", Gstr3bBucket.ZERO_RATED),
        (OutwardSection.SEZ, "sez", Gstr3bBucket.ZERO_RATED),
        (OutwardSection.CDNUR, "export", Gstr3bBucket.ZERO_RATED),
        (OutwardSection.CDNUR, "interstate", Gstr3bBucket.TAXABLE),
        (OutwardSection.NIL_EXEMPT, "intrastate", Gstr3bBucket.NIL_EXEMPT),
        (OutwardSection.B2B_RCM, "intrastate", Gstr3bBucket.REVERSE_CHARGE_OUTWARD),
    ],
)
def test_gstr3b_bucket(section, supply_type, expected):
    assert gstr3b_bucket(section, supply_type) is expected


@pytest.mark.parametrize(
    "bucket, supply_type, gstin, expected",
    [
        (Gstr3bBucket.TAXABLE, "interstate", None, True),
        (Gstr3bBucket.TAXABLE, "interstate", "29EEEEE4444E1Z5", False),   # registered buyer
        (Gstr3bBucket.TAXABLE, "intrastate", None, False),                # same state
        (Gstr3bBucket.ZERO_RATED, "interstate", None, False),
        (Gstr3bBucket.NIL_EXEMPT, "interstate", None, False),
    ],
)
def test_table_3_2_membership(bucket, supply_type, gstin, expected):
    assert belongs_in_table_3_2(bucket, supply_type, gstin) is expected
