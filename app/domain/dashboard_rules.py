from __future__ import annotations

import calendar
from datetime import date


def month_bounds(today: date) -> tuple[date, date]:
    """First and last day of the month containing `today`."""
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1), today.replace(day=last_day)