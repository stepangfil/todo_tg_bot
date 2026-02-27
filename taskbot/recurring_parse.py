"""Парсер текстового ввода расписания повторяющегося напоминания."""
from __future__ import annotations

import re
from typing import Union

# Результат: dict или "INVALID"
ParseResult = Union[dict, str]

# Короткие названия месяцев для форматирования (индекс 1-12, индекс 0 не используется)
MONTHS_SHORT = ("", "янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")

MONTHS_RU: dict[str, int] = {
    "январь": 1, "января": 1, "январе": 1, "январского": 1,
    "февраль": 2, "февраля": 2, "феврале": 2,
    "март": 3, "марта": 3, "марте": 3,
    "апрель": 4, "апреля": 4, "апреле": 4,
    "май": 5, "мая": 5, "мае": 5,
    "июнь": 6, "июня": 6, "июне": 6,
    "июль": 7, "июля": 7, "июле": 7,
    "август": 8, "августа": 8, "августе": 8,
    "сентябрь": 9, "сентября": 9, "сентябре": 9,
    "октябрь": 10, "октября": 10, "октябре": 10,
    "ноябрь": 11, "ноября": 11, "ноябре": 11,
    "декабрь": 12, "декабря": 12, "декабре": 12,
}

_YEARLY_KW = (
    "каждого года", "каждый год", "каждом году",
    "ежегодно", "раз в год", "в год", "каждый год",
)
_MONTHLY_KW = (
    "каждого месяца", "каждый месяц", "каждом месяце",
    "ежемесячно", "раз в месяц", "числа каждого", "число каждого",
)


def parse_recurring_schedule(text: str) -> ParseResult:
    """
    Принимает произвольный текст, возвращает:
      {"repeat_kind": "MONTHLY", "day": int}
      {"repeat_kind": "YEARLY", "day": int, "month": int}
      "INVALID" — если не распознано

    Примеры ввода:
      "каждый месяц 5-го"
      "15 числа каждого месяца"
      "ежемесячно 28"
      "5"                          → MONTHLY, день 5
      "15 ноября каждого года"
      "ежегодно 15 ноября"
      "каждый год 1 марта"
      "1 января"                   → YEARLY, 1 января
      "30 ноября"                  → YEARLY, 30 ноября
      "последнее число"            → MONTHLY, день 28
    """
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)

    # Специальный случай: "последнее число / последний день"
    if re.search(r"последн", s):
        return {"repeat_kind": "MONTHLY", "day": 28}

    # Убираем окончания числительных: 5-го → 5, 15-е → 15
    s = re.sub(r"(\d+)-(?:го|е|й|му|ом|м|х|ми|тый|ой|ый)\b", r"\1", s)

    # Ищем название месяца
    found_month: int | None = None
    s_clean = s
    for m_name, m_num in sorted(MONTHS_RU.items(), key=lambda x: -len(x[0])):
        if m_name in s_clean:
            found_month = m_num
            s_clean = s_clean.replace(m_name, " ").strip()
            break

    is_yearly = any(kw in s for kw in _YEARLY_KW)
    is_monthly = any(kw in s for kw in _MONTHLY_KW)

    # Ищем первое число в очищенной строке
    day_match = re.search(r"\b(\d{1,2})\b", s_clean)
    day = int(day_match.group(1)) if day_match else None

    # --- Годовые ---
    if found_month is not None:
        if day is None:
            day = 1
        day = min(day, _max_day(found_month))
        if not 1 <= day <= 31:
            return "INVALID"
        return {"repeat_kind": "YEARLY", "day": day, "month": found_month}

    # Явно указано "каждый год", но без месяца — не знаем дату
    if is_yearly and found_month is None:
        return "INVALID"

    # --- Ежемесячные ---
    if is_monthly:
        if day is None:
            return "INVALID"
        if not 1 <= day <= 28:
            return "INVALID"
        return {"repeat_kind": "MONTHLY", "day": day}

    # Просто число — трактуем как день месяца
    if day is not None and not is_yearly:
        if 1 <= day <= 28:
            return {"repeat_kind": "MONTHLY", "day": day}
        if 29 <= day <= 31:
            # Округляем до 28, чтобы срабатывало в любом месяце
            return {"repeat_kind": "MONTHLY", "day": 28}

    return "INVALID"


def _max_day(month: int) -> int:
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    if month in (4, 6, 9, 11):
        return 30
    return 29  # февраль с запасом
