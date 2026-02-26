from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from .config import TZ

logger = logging.getLogger(__name__)


@dataclass
class Task:
    id: int
    chat_id: int
    text: str
    done: bool
    remind_at: Optional[datetime]
    reminded: bool
    deleted: bool
    owner_id: Optional[int]
    owner_name: Optional[str]
    reminder_message_id: Optional[int]

    @classmethod
    def from_row(cls, chat_id: int, row: Mapping[str, Any]) -> "Task":
        """Преобразование sqlite Row в доменную модель Task."""
        raw_remind = row.get("remind_at") if hasattr(row, "get") else row["remind_at"]
        remind_at: Optional[datetime]
        if raw_remind:
            try:
                dt = datetime.fromisoformat(raw_remind)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TZ)
                remind_at = dt
            except Exception:
                logger.debug("Task.from_row: invalid remind_at", exc_info=True)
                remind_at = None
        else:
            remind_at = None

        # sqlite Row не всегда поддерживает .get, поэтому аккуратно проверяем наличие полей
        keys = set(row.keys())

        def _get_opt(name: str) -> Optional[Any]:
            return row[name] if name in keys else None

        return cls(
            id=int(row["id"]),
            chat_id=chat_id,
            text=row["text"],
            done=bool(row["done"]) if "done" in keys else False,
            remind_at=remind_at,
            reminded=bool(row["reminded"]) if "reminded" in keys else False,
            deleted=bool(row["deleted"]) if "deleted" in keys else False,
            owner_id=_get_opt("owner_id"),
            owner_name=_get_opt("owner_name"),
            reminder_message_id=_get_opt("reminder_message_id"),
        )

