"""Повторяющиеся напоминания: джоба раз в минуту, отправка и сдвиг next_run_at."""
from __future__ import annotations

import logging
from datetime import datetime

from telegram.ext import Application, ContextTypes

from .config import TZ, RECURRING_DEFAULT_HOUR, RECURRING_DEFAULT_MINUTE
from . import db
from .recurring_logic import compute_next_run

logger = logging.getLogger(__name__)

RECURRING_JOB_INTERVAL_SEC = 60


async def _recurring_tick(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)  # UTC-сравнимое время для выборки due
    now_iso = now.isoformat()
    rows = db.recurring_fetch_due(now_iso)
    for row in rows:
        rec_id = row["id"]
        chat_id = row["chat_id"]
        text = row["text"]
        repeat_kind = row["repeat_kind"]
        day_of_month = row["day_of_month"]
        month = row.get("month")
        hour = row.get("hour") or RECURRING_DEFAULT_HOUR
        minute = row.get("minute") or RECURRING_DEFAULT_MINUTE
        chat_tz = db.get_chat_tz(chat_id)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔄 Напоминание: {text}",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.warning("recurring send failed chat_id=%s rec_id=%s", chat_id, rec_id, exc_info=True)
        next_dt = compute_next_run(
            repeat_kind=repeat_kind,
            day_of_month=day_of_month,
            from_dt=datetime.now(chat_tz),
            month=month,
            hour=hour,
            minute=minute,
        )
        next_iso = next_dt.isoformat()
        db.recurring_update_next_run(rec_id, next_iso)


def start_recurring_job(app: Application):
    if app.job_queue is None:
        return
    app.job_queue.run_repeating(
        _recurring_tick,
        interval=RECURRING_JOB_INTERVAL_SEC,
        first=RECURRING_JOB_INTERVAL_SEC,
        name="recurring_reminders",
    )
