import logging

from telegram import Chat
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def is_group(chat: Chat) -> bool:
    t = (chat.type or "").lower()
    return t in ("group", "supergroup")


async def is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        logger.warning("is_admin failed chat_id=%s user_id=%s", chat_id, user_id, exc_info=True)
        return False


async def can_action(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat: Chat,
    actor_id: int,
    action: str,
    task_owner_id: int | None,
) -> bool:
    # Private chat: allow all
    if (chat.type or "").lower() == "private":
        return True

    # Group checklist rules:
    # DONE, ADD => anyone
    if action in ("ADD", "DONE", "LIST", "HIST"):
        return True

    # REM, DELETE => author or admin
    if action in ("REM", "DELETE"):
        if task_owner_id is not None and actor_id == task_owner_id:
            return True
        return await is_admin(context, chat.id, actor_id)

    return False