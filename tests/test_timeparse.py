"""Тесты парсера времени напоминаний."""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from taskbot.timeparse import parse_remind_time

TZ = ZoneInfo("Europe/Moscow")


@pytest.fixture
def now():
    """Фиксированное «сейчас»: 15 июня 2025, 12:00."""
    return datetime(2025, 6, 15, 12, 0, 0, tzinfo=TZ)


def test_no_reminder(now):
    for s in ("нет", "no", "none", "-", "  НЕТ  "):
        assert parse_remind_time(s, now) is None


def test_through_minutes(now):
    r = parse_remind_time("через 30 мин", now)
    assert r is not None
    assert r == now.replace(hour=12, minute=30, second=0, microsecond=0)

    r = parse_remind_time("через 5 минут", now)
    assert r is not None
    assert (r - now).total_seconds() == 5 * 60


def test_through_hours(now):
    r = parse_remind_time("через 2 часа", now)
    assert r is not None
    assert r == now.replace(hour=14, minute=0, second=0, microsecond=0)


def test_tomorrow_time(now):
    r = parse_remind_time("завтра 10:00", now)
    assert r is not None
    assert r.day == 16
    assert r.month == 6
    assert r.hour == 10
    assert r.minute == 0


def test_today_time_same_day(now):
    r = parse_remind_time("18:00", now)
    assert r is not None
    assert r.day == 15
    assert r.hour == 18
    assert r.minute == 0


def test_today_time_tomorrow_if_passed(now):
    r = parse_remind_time("10:00", now)
    assert r is not None
    assert r.day == 16
    assert r.hour == 10


def test_date_time(now):
    r = parse_remind_time("25.12 09:00", now)
    assert r is not None
    assert r.day == 25
    assert r.month == 12
    assert r.hour == 9
    assert r.minute == 0


def test_invalid_returns_string(now):
    assert parse_remind_time("что-то непонятное", now) == "INVALID"
    assert parse_remind_time("", now) == "INVALID"
