"""Тесты бизнес-логики: services.py (db — реальная in-memory, app — mock)."""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TZ_NAME", "Asia/Bangkok")

import taskbot.db as db
import taskbot.services as services


def make_app():
    app = MagicMock()
    app.job_queue = None
    return app


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "svc.db")
    monkeypatch.setattr(db, "DB_PATH", db_file)
    import taskbot.config as cfg
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    db.db_init()
    yield


# --- add_task ---

def test_add_task_creates_record():
    app = make_app()
    tid = services.add_task(chat_id=1, owner_id=10, owner_name="Иван", text="задача")
    row = db.fetch_task(1, tid)
    assert row is not None
    assert row["text"] == "задача"
    assert row["done"] == 0


def test_add_task_logs_audit():
    services.add_task(chat_id=1, owner_id=10, owner_name="Иван", text="задача")
    logs = db.audit_fetch(1)
    assert any(r["action"] == "ADD" for r in logs)


# --- mark_done ---

def test_mark_done_returns_true():
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "задача")
    ok = services.mark_done(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    assert ok is True
    row = db.fetch_task(1, tid)
    assert row["done"] == 1


def test_mark_done_returns_false_second_time():
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "задача")
    services.mark_done(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    ok2 = services.mark_done(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    assert ok2 is False


def test_mark_done_logs_audit():
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "задача")
    services.mark_done(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    logs = db.audit_fetch(1)
    assert any(r["action"] == "DONE" for r in logs)


# --- delete_task ---

def test_delete_task():
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "удалить меня")
    ok = services.delete_task(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    assert ok is True
    rows = db.fetch_tasks(1)
    assert all(r["id"] != tid for r in rows)


def test_delete_task_logs_audit():
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "задача")
    services.delete_task(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    logs = db.audit_fetch(1)
    assert any(r["action"] == "DELETE" for r in logs)


# --- set_reminder / clear_reminder ---

def test_set_reminder_writes_db():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "задача")
    remind_at = datetime(2025, 12, 25, 10, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
    services.set_reminder(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid, remind_at=remind_at)
    row = db.fetch_task(1, tid)
    assert row["remind_at"] is not None


def test_clear_reminder_removes_remind_at():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "задача")
    remind_at = datetime(2025, 12, 25, 10, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
    services.set_reminder(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid, remind_at=remind_at)
    services.clear_reminder(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    row = db.fetch_task(1, tid)
    assert row["remind_at"] is None


def test_clear_reminder_no_log_if_nothing():
    """clear_reminder не пишет аудит, если напоминания не было."""
    app = make_app()
    tid = db.insert_task(1, 10, "Иван", "задача")
    services.clear_reminder(app=app, chat_id=1, actor_id=10, actor_name="Иван", task_id=tid)
    logs = db.audit_fetch(1)
    assert not any(r["action"] == "REM_CLEAR" for r in logs)
