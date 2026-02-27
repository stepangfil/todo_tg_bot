import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application
from telegram.error import BadRequest

from .config import (
    TZ, FLASH_SECONDS_DEFAULT,
    PICK_DONE_LIMIT, PICK_DEL_LIMIT, PICK_REM_LIMIT,
    TASK_TEXT_MAX_LEN, MAX_TASKS_PER_CHAT,
    RECURRING_DEFAULT_HOUR, RECURRING_DEFAULT_MINUTE,
    SCHEDULE_DELETE_SECONDS,
)
from . import db, services
from .callbacks import CB, parse_callback
from .ui import (
    panel_keyboard,
    format_tasks_text,
    render_panel,
    remind_quick_keyboard,
    Screen,
)
from .timeparse import parse_remind_time
from .permissions import can_action
from .reminders import cancel_reminder, cancel_reminder_repeat
from .models import Task
from .recurring_logic import compute_next_run
from .recurring_parse import parse_recurring_schedule, MONTHS_SHORT
from .rates import format_usdt_thb

logger = logging.getLogger(__name__)


# ---------- pending state constants ----------
PENDING_ADD_WAIT_TEXT = "ADD_WAIT_TEXT"
PENDING_REM_WAIT_TIME = "REM_WAIT_TIME"
PENDING_REM_WAIT_TIME_TEXT = "REM_WAIT_TIME_TEXT"
PENDING_RECUR_ADD_TEXT = "RECUR_ADD_TEXT"
PENDING_RECUR_ADD_SCHEDULE = "RECUR_ADD_SCHEDULE"
PENDING_RECUR_ADD_CUSTOM_DAY = "RECUR_ADD_CUSTOM_DAY"


# ---------- internal helpers for on_panel_button ----------
async def _handle_reminder_message_action(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    chat_id: int,
    user_id: int,
    actor_name: str,
    parsed,
    q,
) -> None:
    action = parsed.action
    task_id = parsed.task_id
    if not task_id:
        return

    row = db.fetch_task(chat_id, task_id)
    if not row:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=q.message.message_id)
        except Exception:
            logger.debug("delete_message (reminder) failed chat_id=%s msg_id=%s", chat_id, q.message.message_id, exc_info=True)

        await flash_panel(context, chat_id, "ℹ️ Задача не найдена/удалена.")
        cancel_reminder(context.application, chat_id, task_id)
        cancel_reminder_repeat(context.application, chat_id, task_id)
        db.set_task_reminder_message_id(chat_id, task_id, None)
        return

    task = Task.from_row(chat_id, row)
    if task.deleted:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=q.message.message_id)
        except Exception:
            logger.debug("delete_message (reminder) failed chat_id=%s msg_id=%s", chat_id, q.message.message_id, exc_info=True)

        await flash_panel(context, chat_id, "ℹ️ Задача не найдена/удалена.")
        cancel_reminder(context.application, chat_id, task_id)
        cancel_reminder_repeat(context.application, chat_id, task_id)
        db.set_task_reminder_message_id(chat_id, task_id, None)
        return

    if action == "ACK":
        ok = services.mark_done(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
        )

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=q.message.message_id)
        except Exception:
            logger.debug("delete_message (reminder) failed chat_id=%s msg_id=%s", chat_id, q.message.message_id, exc_info=True)

        await flash_panel(context, chat_id, "✅ Готово." if ok else "ℹ️ Уже выполнено.")
        return

    if action == "S30":
        allowed = await can_action(
            context=context,
            chat=chat,
            actor_id=user_id,
            action="REM",
            task_owner_id=task.owner_id,
        )
        if not allowed:
            await flash_panel(context, chat_id, "🚫 Напоминание может менять только автор или админ.")
            return

        _ = services.snooze_30m(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
        )

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=q.message.message_id)
        except Exception:
            logger.debug("delete_message (reminder) failed chat_id=%s msg_id=%s", chat_id, q.message.message_id, exc_info=True)

        db.set_task_reminder_message_id(chat_id, task_id, None)
        await flash_panel(context, chat_id, "⏳ Ок. Отложил на 30 минут.")
        return


# ---------- panel lock ----------
def _get_panel_lock(app: Application, chat_id: int) -> asyncio.Lock:
    locks = app.bot_data.setdefault("panel_locks", {})
    lock = locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        locks[chat_id] = lock
    return lock


async def ensure_panel(app: Application, chat_id: int):
    mid = db.get_panel_message_id(chat_id)
    if mid is not None:
        return

    msg = await app.bot.send_message(
        chat_id=chat_id,
        text=format_tasks_text(chat_id),
        reply_markup=panel_keyboard(),
        disable_web_page_preview=True,
    )
    db.set_panel_message_id(chat_id, msg.message_id)


async def edit_panel(app: Application, chat_id: int, text: str, markup: InlineKeyboardMarkup):
    lock = _get_panel_lock(app, chat_id)
    async with lock:
        await ensure_panel(app, chat_id)
        mid = db.get_panel_message_id(chat_id)
        if mid is None:
            return

        try:
            await app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=mid,
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            return
        except BadRequest as e:
            msg = str(e)
            if "Message is not modified" in msg:
                return
            low = msg.lower()
            if "message to edit not found" in low or "message_id_invalid" in low or "can't be edited" in low:
                db.set_panel_message_id(chat_id, None)
            else:
                return
        except Exception:
            logger.warning("edit_panel: unexpected error chat_id=%s", chat_id, exc_info=True)
            return

        msg2 = await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        db.set_panel_message_id(chat_id, msg2.message_id)


# ---------- UI router helper ----------
async def show_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int, screen: str, payload: dict | None = None):
    text, markup = render_panel(chat_id, screen, payload or {})
    await edit_panel(context.application, chat_id, text, markup)


# ---------- flash ----------
async def flash_panel(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    flash_line: str,
    seconds: float = FLASH_SECONDS_DEFAULT,
):
    # Flash uses router (Screen.FLASH)
    await show_screen(context, chat_id, Screen.FLASH, {"line": flash_line})

    app = context.application
    name = f"flash:{chat_id}"

    async def restore():
        await show_screen(context, chat_id, Screen.LIST)

    if app.job_queue is not None:
        for j in app.job_queue.get_jobs_by_name(name):
            j.schedule_removal()

        async def job_restore(job_context: ContextTypes.DEFAULT_TYPE):
            await restore()

        app.job_queue.run_once(job_restore, when=seconds, name=name, data={})
    else:
        async def sleeper():
            await asyncio.sleep(seconds)
            await restore()

        asyncio.create_task(sleeper())


# ---------- message deletion helpers ----------
async def try_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.debug("try_delete_message failed chat_id=%s message_id=%s", chat_id, message_id, exc_info=True)


async def delete_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if chat_id and message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.debug("delete_job: delete_message failed chat_id=%s message_id=%s", chat_id, message_id, exc_info=True)


def schedule_delete_message(app: Application, chat_id: int, message_id: int, when_seconds: int = 10):
    if app.job_queue is None:
        return
    app.job_queue.run_once(delete_job, when=when_seconds, data={"chat_id": chat_id, "message_id": message_id})


# ---------- handlers ----------
_HELP_TEXT = (
    "<b>📋 Todo-бот — справка</b>\n\n"
    "<b>Команды:</b>\n"
    "/start — открыть панель управления\n"
    "/timezone — посмотреть или изменить часовой пояс\n"
    "/help — эта справка\n\n"
    "<b>Панель управления:</b>\n"
    "➕ Добавить — создать новую задачу\n"
    "✅ Выполнить — отметить задачу выполненной\n"
    "🗑 Удалить — удалить задачу\n"
    "⏰ Напоминание — установить или изменить напоминание\n"
    "🕘 История — история действий\n"
    "🔄 Повторяющиеся — ежемесячные/ежегодные напоминания\n"
    "💱 Курс USDT — текущий курс USDT/THB с Bitkub\n\n"
    "<b>Форматы времени для напоминаний:</b>\n"
    "• <code>через 30 мин</code>\n"
    "• <code>через 2 часа</code>\n"
    "• <code>завтра 10:00</code>\n"
    "• <code>25.12 09:00</code>\n"
    "• <code>нет</code> — убрать напоминание\n\n"
    "<b>Форматы для повторяющихся напоминаний:</b>\n"
    "• <code>5</code> или <code>5-го</code> — каждый месяц 5-го\n"
    "• <code>каждый месяц 15-го</code>\n"
    "• <code>15 ноября</code> — ежегодно 15 ноября\n"
    "• <code>последнее число</code>"
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(_HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)
    schedule_delete_message(context.application, chat_id, msg.message_id, when_seconds=60)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    is_first = db.get_panel_message_id(chat_id) is None

    msg = await update.effective_chat.send_message(
        text=format_tasks_text(chat_id),
        reply_markup=panel_keyboard(),
        disable_web_page_preview=True,
    )
    db.set_panel_message_id(chat_id, msg.message_id)

    if is_first:
        hint_text = (
            "👋 Привет! Это твоя панель управления задачами.\n\n"
            "⬆️ Закрепи это сообщение (Pin), чтобы панель всегда была под рукой.\n\n"
            "Справка: /help\n"
            "Часовой пояс: /timezone"
        )
    else:
        hint_text = "⬆️ Панель управления обновлена."

    hint = await update.effective_chat.send_message(hint_text)
    schedule_delete_message(context.application, hint.chat_id, hint.message_id, when_seconds=SCHEDULE_DELETE_SECONDS)


async def on_panel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    data = q.data or ""
    parsed = parse_callback(data)
    chat = q.message.chat
    chat_id = chat.id
    user = q.from_user
    user_id = user.id
    actor_name = user.full_name

    try:
        await q.answer()
    except Exception:
        logger.debug("callback_query.answer failed", exc_info=True)

    # --- reminder message actions ---
    if parsed.type == "REMINDER_MSG":
        await _handle_reminder_message_action(
            context=context, chat=chat, chat_id=chat_id,
            user_id=user_id, actor_name=actor_name, parsed=parsed, q=q,
        )
        return

    # --- panel actions ---
    if parsed.type == "PANEL":
        action = parsed.action
        if action == CB.LIST:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.LIST)
            return

        if action == CB.HIST:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.HIST)
            return

        if action == CB.ADD:
            db.pending_set(chat_id, user_id, PENDING_ADD_WAIT_TEXT)
            await show_screen(context, chat_id, Screen.ADD_PROMPT)
            return

        if action == CB.DONE:
            db.pending_clear(chat_id, user_id)
            rows = db.fetch_open_tasks(chat_id, limit=PICK_DONE_LIMIT)
            tasks = [Task.from_row(chat_id, r) for r in rows]
            await show_screen(context, chat_id, Screen.PICK_DONE, {"rows": tasks})
            return

        if action == CB.DEL:
            db.pending_clear(chat_id, user_id)
            rows = db.fetch_tasks(chat_id, limit=PICK_DEL_LIMIT)
            tasks = [Task.from_row(chat_id, r) for r in rows]
            await show_screen(context, chat_id, Screen.PICK_DEL, {"rows": tasks})
            return

        if action == CB.REM:
            db.pending_clear(chat_id, user_id)
            rows = db.fetch_open_tasks(chat_id, limit=PICK_REM_LIMIT)
            tasks = [Task.from_row(chat_id, r) for r in rows]
            await show_screen(context, chat_id, Screen.PICK_REM, {"rows": tasks})
            return

        if action == CB.RECUR:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.RECUR_LIST)
            return

        if action == CB.RECUR_ADD:
            db.pending_set(chat_id, user_id, PENDING_RECUR_ADD_TEXT)
            await show_screen(context, chat_id, Screen.RECUR_ADD_PROMPT)
            return

        if action == CB.RECUR_DEL_PICK:
            db.pending_clear(chat_id, user_id)
            rows = db.recurring_fetch_by_chat(chat_id)
            await show_screen(context, chat_id, Screen.RECUR_PICK_DEL, {"rows": rows})
            return

        if action == CB.RATES:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.RATES, {"rate_text": "⏳ Получаю курс..."})
            rate_text = await format_usdt_thb()
            await show_screen(context, chat_id, Screen.RATES, {"rate_text": rate_text})
            return

        if action == CB.RECUR_ADD_CUSTOM:
            p = db.pending_get(chat_id, user_id)
            reminder_text = (p["meta"] or "") if p and p["action"] == PENDING_RECUR_ADD_SCHEDULE else ""
            db.pending_set(chat_id, user_id, PENDING_RECUR_ADD_CUSTOM_DAY, meta=reminder_text)
            await show_screen(context, chat_id, Screen.RECUR_ADD_CUSTOM_DAY, {"reminder_text": reminder_text})
            return

        return

    # --- pickers / RSET ---
    if parsed.type == "PICK_DONE":
        task_id = parsed.task_id
        if not task_id:
            return
        row = db.fetch_task(chat_id, task_id)
        if not row:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return
        task = Task.from_row(chat_id, row)
        if task.deleted:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return
        allowed = await can_action(
            context=context,
            chat=chat,
            actor_id=user_id,
            action="DONE",
            task_owner_id=task.owner_id,
        )
        if not allowed:
            await flash_panel(context, chat_id, "🚫 Отметить выполненной может только автор или админ.")
            return
        ok = services.mark_done(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
        )
        await flash_panel(context, chat_id, "✅ Готово." if ok else "ℹ️ Уже выполнено.")
        return

    if parsed.type == "PICK_DEL":
        task_id = parsed.task_id
        if not task_id:
            return
        row = db.fetch_task(chat_id, task_id)
        if not row:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return
        task = Task.from_row(chat_id, row)
        if task.deleted:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return

        allowed = await can_action(
            context=context,
            chat=chat,
            actor_id=user_id,
            action="DELETE",
            task_owner_id=task.owner_id,
        )
        if not allowed:
            await flash_panel(context, chat_id, "🚫 Удалять может только автор или админ.")
            return

        ok = services.delete_task(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
        )
        await flash_panel(context, chat_id, "🗑 Удалено (скрыто)." if ok else "ℹ️ Не нашёл задачу.")
        return

    if parsed.type == "PICK_REM":
        task_id = parsed.task_id
        if not task_id:
            return
        row = db.fetch_task(chat_id, task_id)
        if not row:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return
        task = Task.from_row(chat_id, row)
        if task.deleted:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return

        allowed = await can_action(
            context=context,
            chat=chat,
            actor_id=user_id,
            action="REM",
            task_owner_id=task.owner_id,
        )
        if not allowed:
            await flash_panel(context, chat_id, "🚫 Напоминание может менять только автор или админ.")
            return

        db.pending_set(chat_id, user_id, PENDING_REM_WAIT_TIME, task_id=task_id)
        await show_screen(context, chat_id, Screen.REM_PROMPT, {"task_id": task_id, "task_text": task.text})
        return

    if parsed.type == "RSET":
        task_id = parsed.task_id
        kind = parsed.action or ""
        if not task_id:
            return

        row = db.fetch_task(chat_id, task_id)
        if not row:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return
        task = Task.from_row(chat_id, row)
        if task.deleted:
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return

        allowed = await can_action(
            context=context,
            chat=chat,
            actor_id=user_id,
            action="REM",
            task_owner_id=task.owner_id,
        )
        if not allowed:
            await flash_panel(context, chat_id, "🚫 Напоминание может менять только автор или админ.")
            return

        if kind == "MANUAL":
            db.pending_set(chat_id, user_id, PENDING_REM_WAIT_TIME_TEXT, task_id=task_id)
            await show_screen(context, chat_id, Screen.REM_MANUAL_PROMPT)
            return

        if kind == "NONE":
            services.clear_reminder(
                app=context.application,
                chat_id=chat_id,
                actor_id=user_id,
                actor_name=actor_name,
                task_id=task_id,
            )
            db.pending_clear(chat_id, user_id)
            await flash_panel(context, chat_id, "✅ Напоминание убрано.")
            return

        chat_tz = db.get_chat_tz(chat_id)
        now_local = datetime.now(chat_tz)
        if kind == "30M":
            dt = now_local + timedelta(minutes=30)
        elif kind == "2H":
            dt = now_local + timedelta(hours=2)
        elif kind == "TOM10":
            base = now_local + timedelta(days=1)
            dt = base.replace(hour=10, minute=0, second=0, microsecond=0)
        else:
            await flash_panel(context, chat_id, "ℹ️ Неизвестная команда.")
            return

        services.set_reminder(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
            remind_at=dt,
        )
        db.pending_clear(chat_id, user_id)
        await flash_panel(context, chat_id, f"✅ Напоминание: {dt.strftime('%d.%m %H:%M')}")
        return

    if parsed.type == "RECUR_DEL":
        rec_id = parsed.task_id
        if not rec_id:
            return
        ok = db.recurring_delete(chat_id, rec_id)
        await show_screen(context, chat_id, Screen.RECUR_LIST)
        if ok:
            await flash_panel(context, chat_id, "🗑 Повторяющееся напоминание удалено.")
        return

    if parsed.type == "RECUR_SCHED":
        act = (parsed.action or "").strip()
        if not act:
            return
        p = db.pending_get(chat_id, user_id)
        if not p or p["action"] != PENDING_RECUR_ADD_SCHEDULE:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.RECUR_LIST)
            return
        reminder_text = (p["meta"] or "").strip()
        if not reminder_text:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.RECUR_LIST)
            return
        parts = act.split(":")
        if len(parts) < 2:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.RECUR_LIST)
            return
        kind_char, day_str = parts[0], parts[1]
        try:
            day = int(day_str)
        except ValueError:
            db.pending_clear(chat_id, user_id)
            await show_screen(context, chat_id, Screen.RECUR_LIST)
            return
        month = None
        if kind_char == "Y" and len(parts) >= 3:
            try:
                month = int(parts[2])
            except ValueError:
                month = None
        repeat_kind = "MONTHLY" if kind_char == "M" else "YEARLY"
        if repeat_kind == "YEARLY" and month is None:
            month = 1
        now_local = datetime.now(db.get_chat_tz(chat_id))
        next_dt = compute_next_run(
            repeat_kind=repeat_kind,
            day_of_month=day,
            from_dt=now_local,
            month=month,
            hour=RECURRING_DEFAULT_HOUR,
            minute=RECURRING_DEFAULT_MINUTE,
        )
        next_iso = next_dt.isoformat()
        db.recurring_insert(
            chat_id=chat_id,
            owner_id=user_id,
            owner_name=actor_name,
            text=reminder_text,
            repeat_kind=repeat_kind,
            day_of_month=day,
            next_run_at_iso=next_iso,
            month=month,
            hour=RECURRING_DEFAULT_HOUR,
            minute=RECURRING_DEFAULT_MINUTE,
        )
        db.pending_clear(chat_id, user_id)
        await flash_panel(context, chat_id, f"✅ Добавлено повторяющееся напоминание. След. раз: {next_dt.strftime('%d.%m %H:%M')}")
        await show_screen(context, chat_id, Screen.RECUR_LIST)
        return


async def cmd_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args:
        current_tz = db.get_chat_tz(chat_id)
        msg = await update.message.reply_text(
            f"🕐 Текущий часовой пояс: <b>{current_tz.key}</b>\n\n"
            "Чтобы изменить, отправь:\n"
            "<code>/timezone Europe/Moscow</code>\n\n"
            "Примеры:\n"
            "• <code>Asia/Bangkok</code> — Bangkok (UTC+7)\n"
            "• <code>Europe/Moscow</code> — Москва (UTC+3)\n"
            "• <code>Europe/London</code> — Лондон\n"
            "• <code>America/New_York</code> — Нью-Йорк\n\n"
            "Полный список: en.wikipedia.org/wiki/List_of_tz_database_time_zones",
            parse_mode="HTML",
        )
        schedule_delete_message(context.application, chat_id, msg.message_id, when_seconds=30)
        return

    from zoneinfo import ZoneInfoNotFoundError
    tz_name = args[0]
    try:
        from zoneinfo import ZoneInfo as _ZI
        _ZI(tz_name)
    except (ZoneInfoNotFoundError, Exception):
        msg = await update.message.reply_text(
            f"❌ Неверный часовой пояс: <code>{tz_name}</code>\n\n"
            "Используй формат: <code>Europe/Moscow</code>, <code>Asia/Bangkok</code> и т.п.",
            parse_mode="HTML",
        )
        schedule_delete_message(context.application, chat_id, msg.message_id, when_seconds=20)
        return

    db.set_chat_tz(chat_id, tz_name)
    msg = await update.message.reply_text(
        f"✅ Часовой пояс установлен: <b>{tz_name}</b>",
        parse_mode="HTML",
    )
    schedule_delete_message(context.application, chat_id, msg.message_id, when_seconds=10)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id
    actor_name = user.full_name
    text = update.message.text.strip()

    p = db.pending_get(chat_id, user_id)
    if not p:
        return

    # delete service message (so chat is clean)
    await try_delete_message(context, chat_id, update.message.message_id)

    action = p["action"]

    if action == PENDING_ADD_WAIT_TEXT:
        if not text:
            await show_screen(
                context,
                chat_id,
                Screen.ADD_PROMPT,
                {"hint": "Введи непустой текст задачи."},
            )
            return
        if len(text) > TASK_TEXT_MAX_LEN:
            await show_screen(
                context,
                chat_id,
                Screen.ADD_PROMPT,
                {"hint": f"Текст слишком длинный ({len(text)} символов, максимум {TASK_TEXT_MAX_LEN})."},
            )
            return
        if MAX_TASKS_PER_CHAT > 0 and db.count_open_tasks(chat_id) >= MAX_TASKS_PER_CHAT:
            await show_screen(
                context,
                chat_id,
                Screen.ADD_PROMPT,
                {"hint": f"Достигнут лимит задач ({MAX_TASKS_PER_CHAT}). Сначала выполни или удали существующие."},
            )
            return
        tid = services.add_task(chat_id=chat_id, owner_id=user_id, owner_name=actor_name, text=text)
        db.pending_set(chat_id, user_id, PENDING_REM_WAIT_TIME, task_id=tid)
        await edit_panel(
            context.application,
            chat_id,
            f"✅ Добавил задачу #{tid}\n\n⏰ Установить напоминание?",
            remind_quick_keyboard(tid),
        )
        return

    if action in (PENDING_REM_WAIT_TIME, PENDING_REM_WAIT_TIME_TEXT):
        task_id = p["task_id"]
        if not task_id:
            db.pending_clear(chat_id, user_id)
            return

        row = db.fetch_task(chat_id, task_id)
        if not row:
            db.pending_clear(chat_id, user_id)
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return
        task = Task.from_row(chat_id, row)
        if task.deleted:
            db.pending_clear(chat_id, user_id)
            await flash_panel(context, chat_id, "ℹ️ Не нашёл задачу.")
            return

        allowed = await can_action(
            context=context,
            chat=update.effective_chat,
            actor_id=user_id,
            action="REM",
            task_owner_id=task.owner_id,
        )
        if not allowed:
            db.pending_clear(chat_id, user_id)
            await flash_panel(context, chat_id, "🚫 Напоминание может менять только автор или админ.")
            return

        parsed = parse_remind_time(text, datetime.now(db.get_chat_tz(chat_id)))
        if parsed == "INVALID":
            await show_screen(
                context,
                chat_id,
                Screen.REM_MANUAL_PROMPT,
                {"hint": "Не понял время. Попробуй примеры ниже."},
            )
            return

        if parsed is None:
            services.clear_reminder(
                app=context.application,
                chat_id=chat_id,
                actor_id=user_id,
                actor_name=actor_name,
                task_id=task_id,
            )
            db.pending_clear(chat_id, user_id)
            await flash_panel(context, chat_id, "✅ Ок. Без напоминания.")
            return

        # parsed is datetime
        services.set_reminder(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
            remind_at=parsed,
        )
        db.pending_clear(chat_id, user_id)
        await flash_panel(context, chat_id, f"✅ Напоминание: {parsed.strftime('%d.%m %H:%M')}")
        return

    if action == PENDING_RECUR_ADD_TEXT:
        if not text:
            await show_screen(
                context,
                chat_id,
                Screen.RECUR_ADD_PROMPT,
                {"hint": "Введи непустой текст."},
            )
            return
        db.pending_set(chat_id, user_id, PENDING_RECUR_ADD_SCHEDULE, meta=text)
        await show_screen(context, chat_id, Screen.RECUR_ADD_SCHEDULE, {"reminder_text": text})
        return

    if action == PENDING_RECUR_ADD_CUSTOM_DAY:
        reminder_text = (p["meta"] or "").strip()
        parsed_sched = parse_recurring_schedule(text)
        if parsed_sched == "INVALID":
            await show_screen(
                context,
                chat_id,
                Screen.RECUR_ADD_CUSTOM_DAY,
                {"reminder_text": reminder_text, "hint": "Не понял расписание. Попробуй примеры ниже."},
            )
            return
        repeat_kind = parsed_sched["repeat_kind"]
        day = parsed_sched["day"]
        month = parsed_sched.get("month")
        now_local = datetime.now(db.get_chat_tz(chat_id))
        next_dt = compute_next_run(
            repeat_kind=repeat_kind,
            day_of_month=day,
            from_dt=now_local,
            month=month,
            hour=RECURRING_DEFAULT_HOUR,
            minute=RECURRING_DEFAULT_MINUTE,
        )
        db.recurring_insert(
            chat_id=chat_id,
            owner_id=user_id,
            owner_name=actor_name,
            text=reminder_text,
            repeat_kind=repeat_kind,
            day_of_month=day,
            next_run_at_iso=next_dt.isoformat(),
            month=month,
            hour=RECURRING_DEFAULT_HOUR,
            minute=RECURRING_DEFAULT_MINUTE,
        )
        db.pending_clear(chat_id, user_id)
        if repeat_kind == "MONTHLY":
            sched_label = f"каждый месяц {day}-го"
        else:
            sched_label = f"каждый год {day} {MONTHS_SHORT[month]}"
        await flash_panel(context, chat_id, f"✅ Добавлено: {sched_label}. След. раз: {next_dt.strftime('%d.%m %H:%M')}")
        await show_screen(context, chat_id, Screen.RECUR_LIST)
        return

    db.pending_clear(chat_id, user_id)
