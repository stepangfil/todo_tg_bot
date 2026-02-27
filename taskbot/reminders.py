from __future__ import annotations

import logging
from datetime import datetime, timedelta

from telegram.error import BadRequest
from telegram.ext import Application, ContextTypes

from .config import TZ, REPEAT_INTERVAL_SEC
from . import db
from .ui import reminder_action_keyboard
from .models import Task

logger = logging.getLogger(__name__)


async def _send_or_edit_reminder(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    task_id: int,
    attempt: int,
):
    row = db.fetch_task(chat_id, task_id)
    if not row:
        return
    task = Task.from_row(chat_id, row)
    if task.deleted or task.done:
        return

    # если напоминание уже сняли — прекращаем
    if task.remind_at is None:
        return

    text = f"⏰ Напоминание по задаче #{task_id}:\n{task.text}"
    if attempt > 0:
        text += f"\n\n(повтор: {attempt})"

    mid = task.reminder_message_id

    # 1) пробуем редактировать существующее сообщение
    if mid:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(mid),
                text=text,
                reply_markup=reminder_action_keyboard(task_id),
                disable_web_page_preview=True,
            )
            return
        except BadRequest:
            # нельзя редактировать / сообщение не найдено / etc.
            pass
        except Exception:
            logger.warning("_send_or_edit_reminder edit failed chat_id=%s task_id=%s mid=%s", chat_id, task_id, mid, exc_info=True)

    # 2) если не получилось — отправляем новое
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reminder_action_keyboard(task_id),
        disable_web_page_preview=True,
    )
    db.set_task_reminder_message_id(chat_id, task_id, msg.message_id)


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    task_id = context.job.data["task_id"]

    row = db.fetch_task(chat_id, task_id)
    if not row:
        return
    task = Task.from_row(chat_id, row)
    if task.deleted or task.done:
        return

    # первое напоминание (attempt=0)
    await _send_or_edit_reminder(context, chat_id, task_id, attempt=0)

    # запускаем повторы пока не нажмут ✅/⏳
    start_reminder_repeat(context.application, chat_id, task_id)
    # intentionally do NOT mark_reminded here


def schedule_reminder(app: Application, chat_id: int, task_id: int, remind_at_local: datetime):
    if app.job_queue is None:
        return

    name = f"remind:{chat_id}:{task_id}"
    for j in app.job_queue.get_jobs_by_name(name):
        j.schedule_removal()

    now = datetime.now(db.get_chat_tz(chat_id))
    delay = (remind_at_local - now).total_seconds()
    if delay <= 0:
        delay = 1

    app.job_queue.run_once(
        reminder_job,
        when=delay,
        name=name,
        data={"chat_id": chat_id, "task_id": task_id},
    )


def cancel_reminder(app: Application, chat_id: int, task_id: int):
    if app.job_queue is None:
        return
    name = f"remind:{chat_id}:{task_id}"
    for j in app.job_queue.get_jobs_by_name(name):
        j.schedule_removal()


# --- repeating reminders every 3 minutes until user reacts ---
async def reminder_repeat_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    task_id = data.get("task_id")
    attempt = int(data.get("attempt", 1))

    if not chat_id or not task_id:
        return

    row = db.fetch_task(chat_id, task_id)
    if not row:
        cancel_reminder_repeat(context.application, chat_id, task_id)
        db.set_task_reminder_message_id(chat_id, task_id, None)
        return
    task = Task.from_row(chat_id, row)
    if task.deleted or task.done:
        cancel_reminder_repeat(context.application, chat_id, task_id)
        db.set_task_reminder_message_id(chat_id, task_id, None)
        return

    if task.remind_at is None:
        cancel_reminder_repeat(context.application, chat_id, task_id)
        db.set_task_reminder_message_id(chat_id, task_id, None)
        return

    await _send_or_edit_reminder(context, chat_id, task_id, attempt=attempt)
    context.job.data["attempt"] = attempt + 1


def start_reminder_repeat(app: Application, chat_id: int, task_id: int):
    if app.job_queue is None:
        return

    name = f"repeat:{chat_id}:{task_id}"
    for j in app.job_queue.get_jobs_by_name(name):
        j.schedule_removal()

    app.job_queue.run_repeating(
        reminder_repeat_job,
        interval=REPEAT_INTERVAL_SEC,
        first=REPEAT_INTERVAL_SEC,
        name=name,
        data={"chat_id": chat_id, "task_id": task_id, "attempt": 1},
    )


def cancel_reminder_repeat(app: Application, chat_id: int, task_id: int):
    if app.job_queue is None:
        return
    name = f"repeat:{chat_id}:{task_id}"
    for j in app.job_queue.get_jobs_by_name(name):
        j.schedule_removal()


def restore_reminders(app: Application):
    if app.job_queue is None:
        return

    now = datetime.now(TZ)  # используем дефолтный TZ для restore (только для расчёта задержки)
    for r in db.fetch_pending_reminders():
        try:
            dt = datetime.fromisoformat(r["remind_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
        except Exception:
            logger.warning("restore_reminders: invalid remind_at for chat_id=%s task_id=%s", r.get("chat_id"), r.get("task_id"), exc_info=True)
            continue

        chat_id = int(r["chat_id"])
        task_id = int(r["task_id"])
        if dt <= now:
            schedule_reminder(app, chat_id, task_id, now + timedelta(seconds=3))
        else:
            schedule_reminder(app, chat_id, task_id, dt)
