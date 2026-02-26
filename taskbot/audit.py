import json
import logging
from typing import Optional, Any

from . import db

logger = logging.getLogger(__name__)


def log_action(chat_id: int, actor_id: int, actor_name: str, action: str, task_id: Optional[int] = None, meta: Optional[dict[str, Any]] = None):
    # Best-effort: audit must not crash the bot.
    try:
        meta_str = json.dumps(meta, ensure_ascii=False) if meta is not None else None
        db.audit_insert(chat_id, actor_id, actor_name, action, task_id, meta_str)
    except Exception:
        logger.exception("audit log_action failed chat_id=%s action=%s task_id=%s", chat_id, action, task_id)