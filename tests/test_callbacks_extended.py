"""Тесты новых типов callback: RECUR_DEL, RECUR_SCHED, RSCHED, RECUR_ADD_CUSTOM."""
import pytest
from taskbot.callbacks import (
    parse_callback, CB,
    cb_recur_del, cb_recur_sched,
)


def test_recur_del_parse():
    cb = cb_recur_del(7)
    p = parse_callback(cb)
    assert p.type == "RECUR_DEL"
    assert p.task_id == 7


def test_recur_del_invalid_id():
    p = parse_callback("RECUR_DEL:abc")
    assert p.type == "RECUR_DEL"
    assert p.task_id is None


def test_rsched_monthly():
    cb = cb_recur_sched("M", 5)
    assert cb == "RSCHED:M:5"
    p = parse_callback(cb)
    assert p.type == "RECUR_SCHED"
    assert p.action == "M:5"


def test_rsched_yearly():
    cb = cb_recur_sched("Y", 15, 12)
    assert cb == "RSCHED:Y:15:12"
    p = parse_callback(cb)
    assert p.type == "RECUR_SCHED"
    assert p.action == "Y:15:12"


def test_recur_panel_actions():
    for data in (CB.RECUR, CB.RECUR_ADD, CB.RECUR_ADD_CUSTOM, CB.RECUR_DEL_PICK):
        p = parse_callback(data)
        assert p.type == "PANEL"
        assert p.action == data


def test_rates_panel_action():
    p = parse_callback(CB.RATES)
    assert p.type == "PANEL"
    assert p.action == CB.RATES


def test_unknown_callback():
    p = parse_callback("UNKNOWN:DATA:123")
    assert p.type == "UNKNOWN"


def test_empty_callback():
    p = parse_callback("")
    assert p.type == "UNKNOWN"
