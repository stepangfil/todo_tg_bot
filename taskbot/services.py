# taskbot/services.py
from __future__ import annotations

from datetime import datetime, timedelta

from telegram.ext import Application

from .config import TZ
from . import db
from .audit import log_action
from .models import Task
from .reminders import (
    schedule_reminder,
    cancel_reminder,
    start_reminder_repeat,
    cancel_reminder_repeat,
)


def add_task(*, chat_id: int, owner_id: int, owner_name: str, text: str) -> int:
    tid = db.insert_task(chat_id, owner_id=owner_id, owner_name=owner_name, text=text)
    log_action(chat_id, owner_id, owner_name, "ADD", tid)
    return tid


def set_reminder(
    *,
    app: Application,
    chat_id: int,
    actor_id: int,
    actor_name: str,
    task_id: int,
    remind_at: datetime,
) -> None:
    db.set_task_remind(chat_id, task_id, remind_at.isoformat())
    schedule_reminder(app, chat_id, task_id, remind_at)

    # сбросить повтор (чтобы начинался заново)
    cancel_reminder_repeat(app, chat_id, task_id)

    log_action(chat_id, actor_id, actor_name, "REM_SET", task_id, meta={"remind_at": remind_at.isoformat()})


def clear_reminder(
    *,
    app: Application,
    chat_id: int,
    actor_id: int,
    actor_name: str,
    task_id: int,
) -> None:
    row = db.fetch_task(chat_id, task_id)
    task = Task.from_row(chat_id, row) if row else None
    had_reminder = bool(task and task.remind_at is not None)

    db.set_task_remind(chat_id, task_id, None)
    cancel_reminder(app, chat_id, task_id)
    cancel_reminder_repeat(app, chat_id, task_id)
    db.set_task_reminder_message_id(chat_id, task_id, None)

    # логируем только если реально что-то очищали
    if had_reminder:
        log_action(chat_id, actor_id, actor_name, "REM_CLEAR", task_id)


def snooze_30m(
    *,
    app: Application,
    chat_id: int,
    actor_id: int,
    actor_name: str,
    task_id: int,
) -> datetime:
    cancel_reminder(app, chat_id, task_id)
    cancel_reminder_repeat(app, chat_id, task_id)

    dt = datetime.now(TZ) + timedelta(minutes=30)
    db.set_task_remind(chat_id, task_id, dt.isoformat())
    schedule_reminder(app, chat_id, task_id, dt)

    log_action(chat_id, actor_id, actor_name, "SNOOZE_30M", task_id, meta={"remind_at": dt.isoformat()})
    return dt


def mark_done(
    *,
    app: Application,
    chat_id: int,
    actor_id: int,
    actor_name: str,
    task_id: int,
) -> bool:
    ok = db.mark_done(chat_id, task_id, done_by_id=actor_id, done_by_name=actor_name)
    log_action(chat_id, actor_id, actor_name, "DONE", task_id)

    cancel_reminder(app, chat_id, task_id)
    cancel_reminder_repeat(app, chat_id, task_id)
    db.set_task_remind(chat_id, task_id, None)
    db.mark_reminded(chat_id, task_id)
    db.set_task_reminder_message_id(chat_id, task_id, None)
    return ok


def delete_task(
    *,
    app: Application,
    chat_id: int,
    actor_id: int,
    actor_name: str,
    task_id: int,
) -> bool:
    ok = db.soft_delete(chat_id, task_id)
    log_action(chat_id, actor_id, actor_name, "DELETE", task_id)

    cancel_reminder(app, chat_id, task_id)
    cancel_reminder_repeat(app, chat_id, task_id)
    db.set_task_reminder_message_id(chat_id, task_id, None)
    return ok