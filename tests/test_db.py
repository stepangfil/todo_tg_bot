"""Тесты операций с базой данных (in-memory SQLite)."""
import os
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

# Переключаем DB на in-memory до импорта taskbot
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("TZ_NAME", "Asia/Bangkok")

import taskbot.db as db

TZ = ZoneInfo("Asia/Bangkok")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Каждый тест получает чистую БД в temp-файле."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", db_file)
    # патчим конфиг тоже
    import taskbot.config as cfg
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    db.db_init()
    yield


# --- tasks ---

def test_insert_and_fetch_task():
    tid = db.insert_task(chat_id=1, owner_id=10, owner_name="Иван", text="купить хлеб")
    assert isinstance(tid, int)
    row = db.fetch_task(chat_id=1, task_id=tid)
    assert row is not None
    assert row["text"] == "купить хлеб"
    assert row["done"] == 0
    assert row["deleted"] == 0


def test_fetch_tasks_returns_list():
    db.insert_task(1, 10, "Иван", "задача 1")
    db.insert_task(1, 10, "Иван", "задача 2")
    rows = db.fetch_tasks(chat_id=1)
    assert len(rows) == 2


def test_fetch_open_tasks_excludes_done():
    t1 = db.insert_task(1, 10, "Иван", "открытая")
    t2 = db.insert_task(1, 10, "Иван", "выполненная")
    db.mark_done(chat_id=1, task_id=t2, done_by_id=10, done_by_name="Иван")
    rows = db.fetch_open_tasks(chat_id=1)
    ids = [r["id"] for r in rows]
    assert t1 in ids
    assert t2 not in ids


def test_mark_done():
    tid = db.insert_task(1, 10, "Иван", "задача")
    ok = db.mark_done(1, tid, done_by_id=10, done_by_name="Иван")
    assert ok is True
    row = db.fetch_task(1, tid)
    assert row["done"] == 1


def test_mark_done_idempotent():
    tid = db.insert_task(1, 10, "Иван", "задача")
    db.mark_done(1, tid, 10, "Иван")
    ok2 = db.mark_done(1, tid, 10, "Иван")
    assert ok2 is False


def test_soft_delete():
    tid = db.insert_task(1, 10, "Иван", "задача")
    ok = db.soft_delete(chat_id=1, task_id=tid)
    assert ok is True
    rows = db.fetch_tasks(chat_id=1)
    assert all(r["id"] != tid for r in rows)


def test_set_and_fetch_remind():
    tid = db.insert_task(1, 10, "Иван", "задача")
    iso = datetime(2025, 12, 25, 10, 0, tzinfo=TZ).isoformat()
    db.set_task_remind(1, tid, iso)
    row = db.fetch_task(1, tid)
    assert row["remind_at"] == iso


def test_fetch_pending_reminders():
    tid = db.insert_task(1, 10, "Иван", "задача с напоминанием")
    past = datetime(2020, 1, 1, 10, 0, tzinfo=TZ).isoformat()
    db.set_task_remind(1, tid, past)
    rows = db.fetch_pending_reminders()
    task_ids = [r["task_id"] for r in rows]
    assert tid in task_ids


# --- pending ---

def test_pending_set_get_clear():
    db.pending_set(chat_id=1, user_id=10, action="ADD_WAIT_TEXT")
    p = db.pending_get(1, 10)
    assert p is not None
    assert p["action"] == "ADD_WAIT_TEXT"
    db.pending_clear(1, 10)
    assert db.pending_get(1, 10) is None


def test_pending_meta():
    db.pending_set(1, 10, "RECUR_ADD_SCHEDULE", meta="кредит")
    p = db.pending_get(1, 10)
    assert p["meta"] == "кредит"


def test_pending_upsert():
    db.pending_set(1, 10, "A")
    db.pending_set(1, 10, "B")
    p = db.pending_get(1, 10)
    assert p["action"] == "B"


# --- audit ---

def test_audit_insert_and_fetch():
    db.audit_insert(chat_id=1, actor_id=10, actor_name="Иван", action="ADD", task_id=1, meta=None)
    rows = db.audit_fetch(chat_id=1)
    assert len(rows) == 1
    assert rows[0]["action"] == "ADD"


def test_audit_fetch_limit():
    for i in range(30):
        db.audit_insert(1, 10, "Иван", "ADD", i, None)
    rows = db.audit_fetch(1, limit=10)
    assert len(rows) == 10


# --- recurring_reminders ---

def test_recurring_insert_and_fetch():
    iso = datetime(2025, 3, 5, 10, 0, tzinfo=TZ).isoformat()
    rid = db.recurring_insert(
        chat_id=1, owner_id=10, owner_name="Иван",
        text="кредит", repeat_kind="MONTHLY",
        day_of_month=5, next_run_at_iso=iso,
    )
    rows = db.recurring_fetch_by_chat(chat_id=1)
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert rows[0]["text"] == "кредит"


def test_recurring_delete():
    iso = datetime(2025, 3, 5, 10, 0, tzinfo=TZ).isoformat()
    rid = db.recurring_insert(1, 10, "Иван", "страховка", "YEARLY", 15, iso, month=12)
    ok = db.recurring_delete(chat_id=1, rec_id=rid)
    assert ok is True
    assert db.recurring_fetch_by_chat(1) == []


def test_recurring_update_next_run():
    iso = datetime(2025, 3, 5, 10, 0, tzinfo=TZ).isoformat()
    rid = db.recurring_insert(1, 10, "Иван", "кредит", "MONTHLY", 5, iso)
    new_iso = datetime(2025, 4, 5, 10, 0, tzinfo=TZ).isoformat()
    db.recurring_update_next_run(rid, new_iso)
    row = db.recurring_fetch_one(1, rid)
    assert row["next_run_at"] == new_iso


def test_recurring_fetch_due():
    past = datetime(2020, 1, 1, 10, 0, tzinfo=TZ).isoformat()
    future = datetime(2099, 1, 1, 10, 0, tzinfo=TZ).isoformat()
    db.recurring_insert(1, 10, "Иван", "прошедшее", "MONTHLY", 1, past)
    db.recurring_insert(1, 10, "Иван", "будущее", "MONTHLY", 1, future)
    now_iso = datetime(2025, 6, 1, 10, 0, tzinfo=TZ).isoformat()
    due = db.recurring_fetch_due(now_iso)
    texts = [r["text"] for r in due]
    assert "прошедшее" in texts
    assert "будущее" not in texts


# --- chat_state ---

def test_panel_message_id():
    db.set_panel_message_id(chat_id=1, message_id=999)
    assert db.get_panel_message_id(1) == 999
    db.set_panel_message_id(1, None)
    assert db.get_panel_message_id(1) is None
