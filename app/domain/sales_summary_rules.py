"""
Sales-summary period rules — PURE functions only.

The database returns one row per DAY; this module decides which week / month /
quarter / financial year a day belongs to. Bucketing lives here, in one place,
instead of being repeated in SQL and Python.

Indian conventions:
  * quarter = Apr-Jun (Q1), Jul-Sep (Q2), Oct-Dec (Q3), Jan-Mar (Q4);
  * "year"  = FINANCIAL year (1 Apr - 31 Mar), not the calendar year;
  * week    = ISO week, Monday to Sunday.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, get_args

from app.domain.gstr1_rules import financial_year_for

Granularity = Literal["week", "month", "quarter", "year"]
GRANULARITIES: tuple[str, ...] = get_args(Granularity)

# More buckets than this is unreadable on a chart and costly to build.
MAX_BUCKETS = 400

_FY_QUARTER_BY_START_MONTH = {4: 1, 7: 2, 10: 3, 1: 4}


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def bucket_start(granularity: str, day: date) -> date:
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    if granularity == "quarter":
        return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    if granularity == "year":
        return date(day.year if day.month >= 4 else day.year - 1, 4, 1)
    raise ValueError(f"unknown granularity '{granularity}'")


def next_bucket_start(granularity: str, start: date) -> date:
    if granularity == "week":
        return start + timedelta(days=7)
    if granularity == "month":
        return _add_months(start, 1)
    if granularity == "quarter":
        return _add_months(start, 3)
    if granularity == "year":
        return _add_months(start, 12)
    raise ValueError(f"unknown granularity '{granularity}'")


def bucket_end(granularity: str, start: date) -> date:
    return next_bucket_start(granularity, start) - timedelta(days=1)


def bucket_label(granularity: str, start: date) -> str:
    if granularity == "week":
        iso_year, iso_week, _ = start.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "month":
        return f"{start.year:04d}-{start.month:02d}"
    if granularity == "quarter":
        return f"FY{financial_year_for(start)} Q{_FY_QUARTER_BY_START_MONTH[start.month]}"
    if granularity == "year":
        return f"FY{financial_year_for(start)}"
    raise ValueError(f"unknown granularity '{granularity}'")


def enumerate_buckets(granularity: str, first_day: date, last_day: date) -> list[date]:
    """Start dates of every bucket that touches [first_day, last_day], oldest first. Empty buckets included."""
    starts: list[date] = []
    current = bucket_start(granularity, first_day)
    while current <= last_day:
        starts.append(current)
        current = next_bucket_start(granularity, current)
    return starts
