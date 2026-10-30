from datetime import date

import pytest

from app.domain.sales_summary_rules import (
    bucket_end,
    bucket_label,
    bucket_start,
    enumerate_buckets,
)


@pytest.mark.parametrize(
    "granularity, day, start, end, label",
    [
        ("week", date(2026, 10, 30), date(2026, 10, 26), date(2026, 11, 1), "2026-W44"),
        ("month", date(2026, 2, 14), date(2026, 2, 1), date(2026, 2, 28), "2026-02"),
        ("month", date(2028, 2, 14), date(2028, 2, 1), date(2028, 2, 29), "2028-02"),   # leap year
        ("quarter", date(2026, 4, 1), date(2026, 4, 1), date(2026, 6, 30), "FY2026-27 Q1"),
        ("quarter", date(2027, 3, 31), date(2027, 1, 1), date(2027, 3, 31), "FY2026-27 Q4"),
        ("year", date(2027, 3, 31), date(2026, 4, 1), date(2027, 3, 31), "FY2026-27"),   # still the old FY
        ("year", date(2027, 4, 1), date(2027, 4, 1), date(2028, 3, 31), "FY2027-28"),
    ],
)
def test_bucket_boundaries_and_labels(granularity, day, start, end, label):
    assert bucket_start(granularity, day) == start
    assert bucket_end(granularity, start) == end
    assert bucket_label(granularity, start) == label


def test_enumerate_includes_empty_months():
    starts = enumerate_buckets("month", date(2026, 4, 15), date(2026, 10, 30))
    assert len(starts) == 7
    assert starts[0] == date(2026, 4, 1)


def test_year_bucket_crosses_calendar_year():
    starts = enumerate_buckets("year", date(2026, 3, 31), date(2026, 4, 1))
    assert starts == [date(2025, 4, 1), date(2026, 4, 1)]


def test_unknown_granularity_is_rejected():
    with pytest.raises(ValueError):
        bucket_start("day", date(2026, 1, 1))
