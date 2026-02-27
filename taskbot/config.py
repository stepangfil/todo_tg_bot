from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import os
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parents[1]

# Часовой пояс можно задать через переменную окружения TZ_NAME, по умолчанию Asia/Bangkok
TZ_NAME = os.getenv("TZ_NAME", "Asia/Bangkok")
TZ = ZoneInfo(TZ_NAME)


def resolve_tz(tz_name: Optional[str]) -> ZoneInfo:
    """Возвращает ZoneInfo по названию, при ошибке — дефолтный TZ."""
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, Exception):
            pass
    return TZ

# Путь к базе можно задать через переменную окружения DB_PATH, по умолчанию tasks.db в корне проекта
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "tasks.db"))

# Повторы напоминаний
REPEAT_INTERVAL_SEC = 180  # 3 minutes
# (алиас на будущее, если в коде будет другое имя)
REMINDER_REPEAT_SECONDS = REPEAT_INTERVAL_SEC

# Флеш-строка (короткое подтверждение в панели)
FLASH_SECONDS_DEFAULT = 2.0

# Лимиты выборок задач для picker-экранов
PICK_DONE_LIMIT = 10
PICK_DEL_LIMIT = 20
PICK_REM_LIMIT = 20

# Максимальная длина текста задачи
TASK_TEXT_MAX_LEN = 500

# Максимальное количество открытых задач на чат (0 = без ограничения)
MAX_TASKS_PER_CHAT = int(os.getenv("MAX_TASKS_PER_CHAT", "100"))

# Значения по умолчанию для повторяющихся напоминаний
RECURRING_DEFAULT_HOUR = 10
RECURRING_DEFAULT_MINUTE = 0

# Через сколько секунд автоматически удалять вспомогательные сообщения
SCHEDULE_DELETE_SECONDS = 10
