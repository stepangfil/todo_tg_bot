"""Тесты форматирования панели и текстов."""
import os
import pytest
from unittest.mock import patch

os.environ.setdefault("TZ_NAME", "Asia/Bangkok")
os.environ.setdefault("DB_PATH", ":memory:")

import taskbot.db as db
from taskbot.ui import (
    format_tasks_text,
    panel_keyboard,
    render_panel,
    Screen,
    _format_task_line,
    recur_schedule_keyboard,
)
from taskbot.models import Task
from taskbot.callbacks import CB


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "ui.db")
    monkeypatch.setattr(db, "DB_PATH", db_file)
    import taskbot.config as cfg
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    db.db_init()
    yield


# --- panel_keyboard ---

def test_panel_keyboard_has_required_buttons():
    kb = panel_keyboard()
    all_cbs = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert CB.LIST in all_cbs
    assert CB.ADD in all_cbs
    assert CB.DONE in all_cbs
    assert CB.DEL in all_cbs
    assert CB.REM in all_cbs
    assert CB.HIST in all_cbs
    assert CB.RECUR in all_cbs
    assert CB.RATES in all_cbs


# --- format_tasks_text ---

def test_format_tasks_empty():
    text = format_tasks_text(chat_id=999)
    assert "нет задач" in text.lower() or "добавить" in text.lower()


def test_format_tasks_shows_tasks():
    db.insert_task(1, 10, "Иван", "первая задача")
    db.insert_task(1, 10, "Иван", "вторая задача")
    text = format_tasks_text(chat_id=1)
    assert "первая задача" in text
    assert "вторая задача" in text


def test_format_tasks_shows_done_checkmark():
    tid = db.insert_task(1, 10, "Иван", "выполненная")
    db.mark_done(1, tid, 10, "Иван")
    text = format_tasks_text(chat_id=1)
    assert "✅" in text


def test_format_tasks_shows_open_diamond():
    db.insert_task(1, 10, "Иван", "открытая задача")
    text = format_tasks_text(chat_id=1)
    assert "🔹" in text


# --- _format_task_line ---

def make_task(**kwargs):
    defaults = dict(
        id=1, chat_id=1, text="задача", done=False,
        remind_at=None, reminded=False, deleted=False,
        owner_id=10, owner_name="Иван", reminder_message_id=None,
    )
    defaults.update(kwargs)
    return Task(**defaults)


def test_task_line_open():
    from zoneinfo import ZoneInfo
    task = make_task(done=False)
    line = _format_task_line(1, task, ZoneInfo("Asia/Bangkok"))
    assert "🔹" in line
    assert "задача" in line


def test_task_line_done():
    from zoneinfo import ZoneInfo
    task = make_task(done=True)
    line = _format_task_line(1, task, ZoneInfo("Asia/Bangkok"))
    assert "✅" in line


def test_task_line_with_reminder():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Bangkok")
    remind = datetime(2025, 12, 25, 10, 0, tzinfo=tz)
    task = make_task(remind_at=remind)
    line = _format_task_line(1, task, tz)
    assert "⏰" in line
    assert "25.12" in line


# --- render_panel ---

def test_render_panel_list():
    db.insert_task(1, 10, "Иван", "задача")
    text, kb = render_panel(chat_id=1, screen=Screen.LIST, payload={})
    assert "задача" in text
    assert kb is not None


def test_render_panel_add_prompt():
    text, kb = render_panel(chat_id=1, screen=Screen.ADD_PROMPT, payload={})
    assert "задачи" in text.lower()


def test_render_panel_add_prompt_with_hint():
    text, kb = render_panel(chat_id=1, screen=Screen.ADD_PROMPT, payload={"hint": "тест подсказки"})
    assert "тест подсказки" in text


def test_render_panel_pick_done_empty():
    text, kb = render_panel(chat_id=1, screen=Screen.PICK_DONE, payload={"rows": []})
    assert "нет" in text.lower()


def test_render_panel_pick_done_with_tasks():
    task = make_task(id=5, text="сделать дело")
    text, kb = render_panel(chat_id=1, screen=Screen.PICK_DONE, payload={"rows": [task]})
    assert "сделать дело" in text or kb is not None


def test_render_panel_rem_manual_prompt_hint():
    text, kb = render_panel(
        chat_id=1,
        screen=Screen.REM_MANUAL_PROMPT,
        payload={"hint": "Не понял время."},
    )
    assert "Не понял время." in text
    assert "через" in text.lower() or "примеры" in text.lower()


def test_render_panel_flash():
    db.insert_task(1, 10, "Иван", "задача")
    text, kb = render_panel(chat_id=1, screen=Screen.FLASH, payload={"line": "✅ Готово."})
    assert "✅ Готово." in text


def test_render_panel_recur_list_empty():
    text, kb = render_panel(chat_id=1, screen=Screen.RECUR_LIST, payload={})
    assert "Повторяющиеся" in text or "повторяющиеся" in text.lower()


def test_render_panel_rates_loading():
    text, kb = render_panel(chat_id=1, screen=Screen.RATES, payload={"rate_text": "⏳ Загрузка..."})
    assert "Загрузка" in text
    cbs = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert CB.RATES in cbs
    assert CB.LIST in cbs


# --- recur_schedule_keyboard ---

def test_recur_schedule_keyboard_has_months():
    kb = recur_schedule_keyboard()
    all_labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("1-го" in l for l in all_labels)
    assert any("Ввести" in l for l in all_labels)
    assert any("Назад" in l for l in all_labels)
