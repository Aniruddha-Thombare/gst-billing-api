"""
GSTR-3B Table 3.1 / 3.2 rules — PURE functions only. No DB, no I/O.

GSTR-3B is a SUMMARY of what GSTR-1 reports. So this module does not
classify invoices again: it takes the GSTR-1 section already decided by
gstr1_rules.classify_outward_line and maps it onto a GSTR-3B row. That keeps
the two returns consistent by construction.
"""

from __future__ import annotations

from enum import Enum

from app.domain.gstr1_rules import OutwardSection
from app.models.enum import SupplyType


class Gstr3bBucket(str, Enum):
    TAXABLE = "taxable"                          # 3.1(a)
    ZERO_RATED = "zero_rated"                    # 3.1(b)  exports and SEZ
    NIL_EXEMPT = "nil_exempt"                    # 3.1(c)
    REVERSE_CHARGE_OUTWARD = "reverse_charge"    # tax is paid by the RECIPIENT; shown separately


_OVERSEAS = (SupplyType.EXPORT.value, SupplyType.SEZ.value)


def gstr3b_bucket(section: OutwardSection, supply_type: str) -> Gstr3bBucket:
    """Which GSTR-3B row does a line from this GSTR-1 section belong to?"""
    if section in (OutwardSection.EXPORT, OutwardSection.SEZ):
        return Gstr3bBucket.ZERO_RATED
    if section is OutwardSection.CDNUR and supply_type in _OVERSEAS:
        return Gstr3bBucket.ZERO_RATED          # credit note on an export reduces zero-rated supplies
    if section is OutwardSection.NIL_EXEMPT:
        return Gstr3bBucket.NIL_EXEMPT
    if section is OutwardSection.B2B_RCM:
        return Gstr3bBucket.REVERSE_CHARGE_OUTWARD
    return Gstr3bBucket.TAXABLE


def belongs_in_table_3_2(bucket: Gstr3bBucket, supply_type: str, party_gstin: str | None) -> bool:
    """
    Table 3.2: "Of the supplies in 3.1(a), inter-state supplies made to
    unregistered persons", reported state-wise.
    Composition dealers and UIN holders also belong here, but the data model
    does not mark them, so only unregistered buyers (no GSTIN) are detected.
    """
    return (
        bucket is Gstr3bBucket.TAXABLE
        and supply_type == SupplyType.INTERSTATE.value
        and party_gstin is None
    )
