"""
Helpers shared by every GST report service (GSTR-1, GSTR-3B, sales summary).
Pure or near-pure: no SQL, no I/O. Kept in one place so each rule exists once.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.core.exceptions import (
    FutureReturnPeriodError,
    GSTR1NotApplicableError,
    InvalidReturnPeriodError,
    TokenInvalidError,
)
from app.domain.gstr1_rules import ReturnPeriod, parse_return_period
from app.models.enum import RegistrationType
from app.schemas.gstr1 import TaxAmounts

# India has no daylight saving, so a fixed +05:30 offset is exact and needs no tz database
# (the zoneinfo module fails on Windows unless the tzdata package is installed).
IST = timezone(timedelta(hours=5, minutes=30))

# A statutory report must never be silently truncated. Beyond these row
# counts the request is rejected with a clear message instead.
MAX_JSON_ROWS = 20_000
MAX_EXPORT_ROWS = 200_000


def today_ist() -> date:
    return datetime.now(IST).date()


def resolve_return_period(label: str) -> ReturnPeriod:
    """'2026-09' -> ReturnPeriod, or a 422 error for a malformed / future month."""
    try:
        period = parse_return_period(label)
    except ValueError as exc:
        raise InvalidReturnPeriodError(label) from exc
    if period.start > today_ist():
        raise FutureReturnPeriodError(label)
    return period


def assert_regular_taxpayer(profile: Any) -> None:
    """GSTR-1 / GSTR-3B are filed by regular taxpayers only."""
    if profile is None:
        # A valid token pointing at a tenant that no longer exists.
        raise TokenInvalidError()
    if profile["registration_type"] != RegistrationType.REGULAR.value:
        raise GSTR1NotApplicableError(str(profile["registration_type"]))


def period_warnings(*, period_label: str, is_period_open: bool, draft_count: int) -> list[str]:
    warnings: list[str] = []
    if is_period_open:
        warnings.append(
            f"Period {period_label} has not finished yet; figures will change until the month closes."
        )
    if draft_count:
        warnings.append(
            f"{draft_count} draft document(s) dated in this period are NOT included. "
            "Send or cancel them before filing."
        )
    return warnings


# ── SMALL DECIMAL HELPERS (shared by the 3B and sales-summary services) ──────

def to_decimal(value: Any) -> Decimal:
    return Decimal(value) if value is not None else Decimal("0.00")


def signed_amounts(amounts: TaxAmounts, sign: Decimal) -> TaxAmounts:
    return TaxAmounts(
        taxable_amount=amounts.taxable_amount * sign,
        igst_amount=amounts.igst_amount * sign,
        cgst_amount=amounts.cgst_amount * sign,
        sgst_amount=amounts.sgst_amount * sign,
        cess_amount=amounts.cess_amount * sign,
    )


def accumulate(target: TaxAmounts, amounts: TaxAmounts) -> None:
    target.taxable_amount += amounts.taxable_amount
    target.igst_amount += amounts.igst_amount
    target.cgst_amount += amounts.cgst_amount
    target.sgst_amount += amounts.sgst_amount
    target.cess_amount += amounts.cess_amount
