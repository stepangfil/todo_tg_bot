from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .config import TZ
from . import db
from .callbacks import CB, cb_done, cb_del, cb_rem, cb_rset, cb_rm_ack, cb_rm_snooze30
from .models import Task

logger = logging.getLogger(__name__)


class Screen:
    LIST = "LIST"
    HIST = "HIST"
    ADD_PROMPT = "ADD_PROMPT"
    PICK_DONE = "PICK_DONE"
    PICK_DEL = "PICK_DEL"
    PICK_REM = "PICK_REM"
    REM_PROMPT = "REM_PROMPT"
    REM_MANUAL_PROMPT = "REM_MANUAL_PROMPT"
    FLASH = "FLASH"


def panel_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("📋 Список", callback_data=CB.LIST),
            InlineKeyboardButton("➕ Добавить", callback_data=CB.ADD),
        ],
        [
            InlineKeyboardButton("✅ Выполнить", callback_data=CB.DONE),
            InlineKeyboardButton("🗑 Удалить", callback_data=CB.DEL),
            InlineKeyboardButton("⏰ Напоминание", callback_data=CB.REM),
        ],
        [
            InlineKeyboardButton("🕘 История", callback_data=CB.HIST),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def remind_quick_keyboard(task_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("❌ Без напоминания", callback_data=cb_rset(task_id, "NONE")),
        ],
        [
            InlineKeyboardButton("⏳ +30 минут", callback_data=cb_rset(task_id, "30M")),
            InlineKeyboardButton("⏳ +2 часа", callback_data=cb_rset(task_id, "2H")),
        ],
        [
            InlineKeyboardButton("☀️ Завтра в 10:00", callback_data=cb_rset(task_id, "TOM10")),
        ],
        [
            InlineKeyboardButton("⌨️ Ввести время текстом", callback_data=cb_rset(task_id, "MANUAL")),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def reminder_action_keyboard(task_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("✅ Готово", callback_data=cb_rm_ack(task_id)),
            InlineKeyboardButton("⏳ +30 минут", callback_data=cb_rm_snooze30(task_id)),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def _format_task_line(idx: int, task: Task) -> str:
    prefix = f"{idx}. "
    status = "✅" if task.done else "🔹"
    text = task.text
    remind_at = task.remind_at

    if remind_at:
        try:
            dt = remind_at.astimezone(TZ)
            time_part = dt.strftime("%d.%m %H:%M")
            remind_str = f" ⏰ {time_part}"
        except Exception:
            logger.debug("_format_task_line: remind_at format failed", exc_info=True)
            remind_str = " ⏰"
    else:
        remind_str = ""

    return f"{prefix}{status} {text}{remind_str}"


def format_tasks_text(chat_id: int) -> str:
    rows = db.fetch_tasks(chat_id, limit=20)
    if not rows:
        return "Пока нет задач.\nНажми «➕ Добавить», чтобы создать первую."

    tasks = [Task.from_row(chat_id, row) for row in rows]

    lines = ["Твои задачи:"]
    for idx, task in enumerate(tasks, start=1):
        lines.append(_format_task_line(idx, task))
    return "\n".join(lines)


# Человекочитаемые подписи для действий в истории
ACTION_LABELS = {
    "ADD": "добавил задачу",
    "DONE": "выполнил задачу",
    "DELETE": "удалил задачу",
    "REM_SET": "поставил напоминание",
    "REM_CLEAR": "убрал напоминание",
    "SNOOZE_30M": "отложил на 30 мин",
}


def _action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def _format_history_text(chat_id: int) -> str:
    rows = db.audit_fetch(chat_id, limit=25)
    if not rows:
        return "Пока нет истории действий."

    lines: list[str] = ["📜 История действий\n"]
    last_date_str: str | None = None
    task_text_cache: dict[int, str] = {}

    for row in rows:
        action = row["action"]
        task_id = row["task_id"]
        created_at = row["created_at"]
        actor = (row["actor_name"] or "").strip() or f"ID{row['actor_id']}"

        try:
            dt = datetime.fromisoformat(created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            dt_local = dt.astimezone(TZ)
            ts = dt_local.strftime("%H:%M")
            date_str = dt_local.strftime("%d.%m.%Y")
        except Exception:
            logger.debug("_format_history_text: created_at format failed", exc_info=True)
            ts = created_at
            date_str = ""

        # Разделитель по дням
        if date_str and date_str != last_date_str:
            if last_date_str is not None:
                lines.append("")
            lines.append(f"▸ {date_str}")
            last_date_str = date_str

        label = _action_label(action)
        part = f"  {ts}  {actor} {label}"
        if task_id is not None:
            part += f" #{task_id}"
            # Опционально: подставить текст задачи (первые 35 символов)
            if task_id not in task_text_cache:
                task_text_cache[task_id] = db.fetch_task_text(chat_id, task_id) or ""
            text = task_text_cache[task_id]
            if text:
                snippet = text[:35] + "…" if len(text) > 35 else text
                part += f" «{snippet}»"
        lines.append(part)

    return "\n".join(lines)


def _tasks_pick_keyboard(rows: Iterable, kind: str) -> InlineKeyboardMarkup:
    """rows: итерация по Task или по row-like (id, text)."""
    buttons: list[list[InlineKeyboardButton]] = []
    MAX_LABEL = 40

    for row in rows:
        tid = row.id if hasattr(row, "id") else row["id"]
        text = row.text if hasattr(row, "text") else row["text"]
        tid = int(tid)
        short = (text[:MAX_LABEL] + "…") if len(text) > MAX_LABEL else text
        if kind == "DEL":
            done = row.done if hasattr(row, "done") else row.get("done", False)
            status = "✅" if done else "🔹"
            label = f"{status} #{tid} {short}"
        else:
            label = f"#{tid} {short}"
        if kind == "DONE":
            cb = cb_done(tid)
        elif kind == "DEL":
            cb = cb_del(tid)
        else:
            cb = cb_rem(tid)
        buttons.append([InlineKeyboardButton(label, callback_data=cb)])

    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB.LIST)])
    return InlineKeyboardMarkup(buttons)


def render_panel(chat_id: int, screen: str, payload: dict) -> Tuple[str, InlineKeyboardMarkup]:
    if screen == Screen.LIST:
        return format_tasks_text(chat_id), panel_keyboard()

    if screen == Screen.HIST:
        return _format_history_text(chat_id), panel_keyboard()

    if screen == Screen.ADD_PROMPT:
        hint = payload.get("hint", "")
        text = "✏️ Отправь текст задачи одним сообщением."
        if hint:
            text = f"{hint}\n\n{text}"
        return text, panel_keyboard()

    if screen == Screen.PICK_DONE:
        rows = payload.get("rows") or []
        if not rows:
            return "Нет открытых задач для выполнения.", panel_keyboard()
        return "Выбери задачу, которую нужно отметить выполненной:", _tasks_pick_keyboard(rows, "DONE")

    if screen == Screen.PICK_DEL:
        rows = payload.get("rows") or []
        if not rows:
            return "Нет задач для удаления.", panel_keyboard()
        return "Выбери задачу, которую нужно удалить:", _tasks_pick_keyboard(rows, "DEL")

    if screen == Screen.PICK_REM:
        rows = payload.get("rows") or []
        if not rows:
            return "Нет задач для настройки напоминаний.", panel_keyboard()
        return "Выбери задачу, для которой нужно настроить напоминание:", _tasks_pick_keyboard(rows, "REM")

    if screen == Screen.REM_PROMPT:
        task_id = payload.get("task_id")
        task_text = payload.get("task_text", "")
        text = f"Задача #{task_id}:\n{task_text}\n\nВыбери быстрый вариант или введи время напоминания текстом."
        return text, remind_quick_keyboard(task_id)

    if screen == Screen.REM_MANUAL_PROMPT:
        hint = payload.get("hint", "")
        text = (
            "Введи время напоминания.\n"
            "Примеры: «через 30 мин», «завтра 10:00», «25.12 09:00», «нет»."
        )
        if hint:
            text = f"{hint}\n\n{text}"
        return text, panel_keyboard()

    if screen == Screen.FLASH:
        line = payload.get("line", "")
        base = format_tasks_text(chat_id)
        return f"{line}\n\n{base}", panel_keyboard()

    # fallback
    return format_tasks_text(chat_id), panel_keyboard()
