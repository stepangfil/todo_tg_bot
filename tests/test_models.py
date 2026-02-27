"""Тесты доменной модели Task.from_row."""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from taskbot.models import Task

TZ = ZoneInfo("Asia/Bangkok")


def make_row(**kwargs):
    defaults = {
        "id": 1,
        "text": "тестовая задача",
        "done": 0,
        "remind_at": None,
        "reminded": 0,
        "deleted": 0,
        "owner_id": 42,
        "owner_name": "Иван",
        "reminder_message_id": None,
    }
    defaults.update(kwargs)
    return defaults


def test_basic_fields():
    row = make_row(id=5, text="купить хлеб", done=0)
    task = Task.from_row(chat_id=100, row=row)
    assert task.id == 5
    assert task.text == "купить хлеб"
    assert task.done is False
    assert task.chat_id == 100
    assert task.deleted is False


def test_done_flag():
    row = make_row(done=1)
    task = Task.from_row(chat_id=1, row=row)
    assert task.done is True


def test_deleted_flag():
    row = make_row(deleted=1)
    task = Task.from_row(chat_id=1, row=row)
    assert task.deleted is True


def test_remind_at_parsed():
    iso = "2025-12-25T10:00:00"
    row = make_row(remind_at=iso)
    task = Task.from_row(chat_id=1, row=row)
    assert task.remind_at is not None
    assert task.remind_at.day == 25
    assert task.remind_at.month == 12
    assert task.remind_at.hour == 10


def test_remind_at_with_tz():
    iso = "2025-12-25T10:00:00+07:00"
    row = make_row(remind_at=iso)
    task = Task.from_row(chat_id=1, row=row)
    assert task.remind_at is not None
    assert task.remind_at.tzinfo is not None


def test_remind_at_none():
    row = make_row(remind_at=None)
    task = Task.from_row(chat_id=1, row=row)
    assert task.remind_at is None


def test_remind_at_invalid_string():
    row = make_row(remind_at="не-дата")
    task = Task.from_row(chat_id=1, row=row)
    assert task.remind_at is None


def test_optional_fields_missing():
    row = {"id": 1, "text": "задача", "done": 0, "remind_at": None, "reminded": 0, "deleted": 0}
    task = Task.from_row(chat_id=1, row=row)
    assert task.owner_id is None
    assert task.owner_name is None
    assert task.reminder_message_id is None
