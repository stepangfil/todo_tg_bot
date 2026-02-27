"""Вычисление следующей даты для повторяющихся напоминаний."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import TZ


def compute_next_run(
    repeat_kind: str,
    day_of_month: int,
    from_dt: datetime,
    month: Optional[int] = None,
    hour: int = 10,
    minute: int = 0,
) -> datetime:
    """Следующая дата срабатывания. from_dt — после какой даты искать."""
    if from_dt.tzinfo is None:
        from_dt = from_dt.replace(tzinfo=TZ)
    if repeat_kind == "MONTHLY":
        year, m = from_dt.year, from_dt.month
        day = min(day_of_month, _days_in_month(year, m))
        candidate = from_dt.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= from_dt:
            m += 1
            if m > 12:
                m = 1
                year += 1
            day = min(day_of_month, _days_in_month(year, m))
            candidate = from_dt.replace(year=year, month=m, day=day, hour=hour, minute=minute, second=0, microsecond=0)
        return candidate
    if repeat_kind == "YEARLY" and month is not None:
        year = from_dt.year
        day = min(day_of_month, _days_in_month(year, month))
        candidate = from_dt.replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= from_dt:
            candidate = candidate.replace(year=year + 1)
            candidate = candidate.replace(day=min(day_of_month, _days_in_month(year + 1, month)))
        return candidate
    return from_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _days_in_month(year: int, month: int) -> int:
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    if month in (4, 6, 9, 11):
        return 30
    return 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
