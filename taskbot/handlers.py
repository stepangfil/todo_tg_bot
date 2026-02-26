import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application
from telegram.error import BadRequest

from .config import TZ, FLASH_SECONDS_DEFAULT
from . import db, services
from .callbacks import CB, parse_callback
from .ui import (
    panel_keyboard,
    format_tasks_text,
    render_panel,
    Screen,
)
from .timeparse import parse_remind_time
from .permissions import can_action
from .reminders import cancel_reminder, cancel_reminder_repeat
from .models import Task

logger = logging.getLogger(__name__)


# ---------- pending state constants ----------
PENDING_ADD_WAIT_TEXT = "ADD_WAIT_TEXT"
PENDING_REM_WAIT_TIME = "REM_WAIT_TIME"
PENDING_REM_WAIT_TIME_TEXT = "REM_WAIT_TIME_TEXT"


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


async def _handle_panel_action(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    parsed,
) -> None:
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
        rows = db.fetch_open_tasks(chat_id, limit=10)
        await show_screen(context, chat_id, Screen.PICK_DONE, {"rows": rows})
        return

    if action == CB.DEL:
        db.pending_clear(chat_id, user_id)
        rows = db.fetch_tasks(chat_id, limit=20)
        await show_screen(context, chat_id, Screen.PICK_DEL, {"rows": rows})
        return

    if action == CB.REM:
        db.pending_clear(chat_id, user_id)
        rows = db.fetch_open_tasks(chat_id, limit=20)
        tasks = [Task.from_row(chat_id, r) for r in rows]
        await show_screen(context, chat_id, Screen.PICK_REM, {"rows": tasks})
        return


async def _handle_pick_or_rset(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    chat_id: int,
    user_id: int,
    actor_name: str,
    parsed,
) -> None:
    if parsed.type == "PICK_DONE":
        task_id = parsed.task_id
        if not task_id:
            return
        ok = services.mark_done(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
        )
        await flash_panel(context, chat_id, "✅ Готово." if ok else "ℹ️ Уже выполнено/не найдено.")
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

        now_local = datetime.now(TZ)
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    msg = await update.effective_chat.send_message(
        text=format_tasks_text(chat_id),
        reply_markup=panel_keyboard(),
        disable_web_page_preview=True,
    )
    db.set_panel_message_id(chat_id, msg.message_id)

    hint = await update.effective_chat.send_message(
        "⬆️ Это панель управления. Можешь закрепить это сообщение в группе (Pin)."
    )
    schedule_delete_message(context.application, hint.chat_id, hint.message_id, when_seconds=10)


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
            rows = db.fetch_open_tasks(chat_id, limit=10)
            tasks = [Task.from_row(chat_id, r) for r in rows]
            await show_screen(context, chat_id, Screen.PICK_DONE, {"rows": tasks})
            return

        if action == CB.DEL:
            db.pending_clear(chat_id, user_id)
            rows = db.fetch_tasks(chat_id, limit=20)
            tasks = [Task.from_row(chat_id, r) for r in rows]
            await show_screen(context, chat_id, Screen.PICK_DEL, {"rows": tasks})
            return

        if action == CB.REM:
            db.pending_clear(chat_id, user_id)
            rows = db.fetch_open_tasks(chat_id, limit=20)
            tasks = [Task.from_row(chat_id, r) for r in rows]
            await show_screen(context, chat_id, Screen.PICK_REM, {"rows": tasks})
            return

        return

    # --- pickers / RSET ---
    if parsed.type == "PICK_DONE":
        task_id = parsed.task_id
        if not task_id:
            return
        ok = services.mark_done(
            app=context.application,
            chat_id=chat_id,
            actor_id=user_id,
            actor_name=actor_name,
            task_id=task_id,
        )
        await flash_panel(context, chat_id, "✅ Готово." if ok else "ℹ️ Уже выполнено/не найдено.")
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

        now_local = datetime.now(TZ)
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
        tid = services.add_task(chat_id=chat_id, owner_id=user_id, owner_name=actor_name, text=text)
        db.pending_set(chat_id, user_id, PENDING_REM_WAIT_TIME, task_id=tid)
        await edit_panel(
            context.application,
            chat_id,
            f"✅ Добавил задачу #{tid}\n\n⏰ Установить напоминание?",
            # оставляем твою текущую клавиатуру (она уже в ui)
            __import__("taskbot.ui", fromlist=["remind_quick_keyboard"]).remind_quick_keyboard(tid),
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

        parsed = parse_remind_time(text, datetime.now(TZ))
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

    db.pending_clear(chat_id, user_id)
