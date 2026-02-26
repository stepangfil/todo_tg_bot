import re
from datetime import datetime, timedelta


def parse_remind_time(text: str, now_local: datetime):
    s = text.strip().lower()

    if s in ("нет", "no", "none", "-"):
        return None

    m = re.match(r"^через\s*(\d+)\s*(м|мин|минут|минуты|h|ч|час|часа|часов)$", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit in ("м", "мин", "минут", "минуты"):
            return now_local + timedelta(minutes=n)
        return now_local + timedelta(hours=n)

    m = re.match(r"^завтра\s*(\d{1,2}):(\d{2})$", s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        base = now_local + timedelta(days=1)
        return base.replace(hour=hh, minute=mm, second=0, microsecond=0)

    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        dt = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dt < now_local:
            dt = dt + timedelta(days=1)
        return dt

    m = re.match(r"^(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        d, mo, hh, mm = map(int, m.groups())
        dt = now_local.replace(month=mo, day=d, hour=hh, minute=mm, second=0, microsecond=0)
        if dt < now_local:
            dt = dt.replace(year=now_local.year + 1)
        return dt

    return "INVALID"
