"""Тесты парсера текстового расписания повторяющихся напоминаний."""
import pytest
from taskbot.recurring_parse import parse_recurring_schedule


# --- Ежемесячные — просто число ---

def test_just_number_monthly():
    r = parse_recurring_schedule("5")
    assert r == {"repeat_kind": "MONTHLY", "day": 5}

def test_number_with_suffix():
    r = parse_recurring_schedule("7-го")
    assert r == {"repeat_kind": "MONTHLY", "day": 7}

def test_number_at_boundary():
    assert parse_recurring_schedule("1") == {"repeat_kind": "MONTHLY", "day": 1}
    assert parse_recurring_schedule("28") == {"repeat_kind": "MONTHLY", "day": 28}

def test_number_above_28_rounds_to_28():
    assert parse_recurring_schedule("29") == {"repeat_kind": "MONTHLY", "day": 28}
    assert parse_recurring_schedule("31") == {"repeat_kind": "MONTHLY", "day": 28}


# --- Ежемесячные — с ключевыми словами ---

def test_kazhdiy_mesyats():
    r = parse_recurring_schedule("каждый месяц 5-го")
    assert r == {"repeat_kind": "MONTHLY", "day": 5}

def test_ezhmesyachno():
    r = parse_recurring_schedule("ежемесячно 15")
    assert r == {"repeat_kind": "MONTHLY", "day": 15}

def test_chisla_kazhdogo_mesyatsa():
    r = parse_recurring_schedule("15 числа каждого месяца")
    assert r == {"repeat_kind": "MONTHLY", "day": 15}

def test_raz_v_mesyats():
    r = parse_recurring_schedule("раз в месяц 10-го")
    assert r == {"repeat_kind": "MONTHLY", "day": 10}

def test_monthly_invalid_day_0():
    r = parse_recurring_schedule("каждый месяц 0-го")
    # 0 - не валидный день, ожидаем INVALID
    assert r == "INVALID"

def test_monthly_no_day():
    assert parse_recurring_schedule("каждый месяц") == "INVALID"


# --- Последнее число ---

def test_poslednee_chislo():
    assert parse_recurring_schedule("последнее число") == {"repeat_kind": "MONTHLY", "day": 28}

def test_posledniy_den():
    assert parse_recurring_schedule("последний день") == {"repeat_kind": "MONTHLY", "day": 28}


# --- Ежегодные — с месяцем ---

def test_yearly_15_noyabrya():
    r = parse_recurring_schedule("15 ноября")
    assert r == {"repeat_kind": "YEARLY", "day": 15, "month": 11}

def test_yearly_kazhdiy_god():
    r = parse_recurring_schedule("каждый год 1 марта")
    assert r == {"repeat_kind": "YEARLY", "day": 1, "month": 3}

def test_yearly_ezhegodno():
    r = parse_recurring_schedule("ежегодно 1 марта")
    assert r == {"repeat_kind": "YEARLY", "day": 1, "month": 3}

def test_yearly_kazhdogo_goda():
    r = parse_recurring_schedule("15 ноября каждого года")
    assert r == {"repeat_kind": "YEARLY", "day": 15, "month": 11}

def test_yearly_1_yanvarya():
    r = parse_recurring_schedule("1 января")
    assert r == {"repeat_kind": "YEARLY", "day": 1, "month": 1}

def test_yearly_25_dekabrya():
    r = parse_recurring_schedule("25 декабря")
    assert r == {"repeat_kind": "YEARLY", "day": 25, "month": 12}

def test_yearly_caps_insensitive():
    r = parse_recurring_schedule("15 НОЯБРЯ каждого года")
    assert r == {"repeat_kind": "YEARLY", "day": 15, "month": 11}

def test_yearly_no_month_invalid():
    assert parse_recurring_schedule("каждый год") == "INVALID"
    assert parse_recurring_schedule("ежегодно") == "INVALID"


# --- INVALID ---

def test_empty_string():
    assert parse_recurring_schedule("") == "INVALID"

def test_garbage():
    assert parse_recurring_schedule("абракадабра") == "INVALID"
    assert parse_recurring_schedule("через год") == "INVALID"

def test_whitespace_only():
    assert parse_recurring_schedule("   ") == "INVALID"
