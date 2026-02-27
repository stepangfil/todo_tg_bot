"""Тесты вычисления следующей даты повторяющегося напоминания."""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from taskbot.recurring_logic import compute_next_run

TZ = ZoneInfo("Asia/Bangkok")


def dt(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, 0, tzinfo=TZ)


# --- MONTHLY ---

def test_monthly_same_month_before_day():
    """from_dt до дня срабатывания — должен дать этот же месяц."""
    from_dt = dt(2025, 3, 1, 9, 0)
    result = compute_next_run("MONTHLY", day_of_month=5, from_dt=from_dt, hour=10, minute=0)
    assert result == dt(2025, 3, 5)

def test_monthly_same_day_before_time():
    """from_dt в день срабатывания, но до часа — тот же день."""
    from_dt = dt(2025, 3, 5, 9, 0)
    result = compute_next_run("MONTHLY", day_of_month=5, from_dt=from_dt, hour=10, minute=0)
    assert result == dt(2025, 3, 5)

def test_monthly_same_day_after_time():
    """from_dt в день срабатывания после часа — следующий месяц."""
    from_dt = dt(2025, 3, 5, 11, 0)
    result = compute_next_run("MONTHLY", day_of_month=5, from_dt=from_dt, hour=10, minute=0)
    assert result == dt(2025, 4, 5)

def test_monthly_after_day():
    """from_dt после дня срабатывания — следующий месяц."""
    from_dt = dt(2025, 3, 20, 10, 0)
    result = compute_next_run("MONTHLY", day_of_month=5, from_dt=from_dt, hour=10, minute=0)
    assert result == dt(2025, 4, 5)

def test_monthly_year_wrap():
    """Декабрь → январь следующего года."""
    from_dt = dt(2025, 12, 20, 10, 0)
    result = compute_next_run("MONTHLY", day_of_month=5, from_dt=from_dt, hour=10, minute=0)
    assert result == dt(2026, 1, 5)

def test_monthly_day_clamped_short_month():
    """31-е в феврале → 28-е (или 29-е в високосный)."""
    from_dt = dt(2025, 1, 31, 11, 0)  # уже после 31-го января
    result = compute_next_run("MONTHLY", day_of_month=31, from_dt=from_dt, hour=10, minute=0)
    assert result.month == 2
    assert result.day <= 29


# --- YEARLY ---

def test_yearly_before_date():
    """from_dt до даты в этом году."""
    from_dt = dt(2025, 3, 1, 10, 0)
    result = compute_next_run("YEARLY", day_of_month=15, from_dt=from_dt, month=11, hour=10, minute=0)
    assert result == dt(2025, 11, 15)

def test_yearly_after_date_next_year():
    """from_dt после даты в этом году → следующий год."""
    from_dt = dt(2025, 12, 1, 10, 0)
    result = compute_next_run("YEARLY", day_of_month=15, from_dt=from_dt, month=11, hour=10, minute=0)
    assert result == dt(2026, 11, 15)

def test_yearly_same_day_before_time():
    from_dt = dt(2025, 11, 15, 9, 0)
    result = compute_next_run("YEARLY", day_of_month=15, from_dt=from_dt, month=11, hour=10, minute=0)
    assert result == dt(2025, 11, 15)

def test_yearly_same_day_after_time():
    from_dt = dt(2025, 11, 15, 11, 0)
    result = compute_next_run("YEARLY", day_of_month=15, from_dt=from_dt, month=11, hour=10, minute=0)
    assert result == dt(2026, 11, 15)

def test_yearly_no_month_returns_fallback():
    """Без month возвращает from_dt с заменой часа (fallback)."""
    from_dt = dt(2025, 3, 1, 9, 0)
    result = compute_next_run("YEARLY", day_of_month=15, from_dt=from_dt, month=None, hour=10, minute=0)
    assert result.hour == 10
    assert result.minute == 0
