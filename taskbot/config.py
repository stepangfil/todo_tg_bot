from zoneinfo import ZoneInfo
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

# Часовой пояс можно задать через переменную окружения TZ_NAME, по умолчанию Asia/Bangkok
TZ_NAME = os.getenv("TZ_NAME", "Asia/Bangkok")
TZ = ZoneInfo(TZ_NAME)

# Путь к базе можно задать через переменную окружения DB_PATH, по умолчанию tasks.db в корне проекта
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "tasks.db"))

# Повторы напоминаний
REPEAT_INTERVAL_SEC = 180  # 3 minutes
# (алиас на будущее, если в коде будет другое имя)
REMINDER_REPEAT_SECONDS = REPEAT_INTERVAL_SEC

# Флеш-строка (короткое подтверждение в панели)
FLASH_SECONDS_DEFAULT = 2.0
