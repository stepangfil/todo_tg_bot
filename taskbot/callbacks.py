# taskbot/callbacks.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class CB:
    # panel actions
    LIST = "A:LIST"
    ADD = "A:ADD"
    DONE = "A:DONE"
    DEL = "A:DEL"
    REM = "A:REM"
    HIST = "A:HIST"
    RECUR = "A:RECUR"
    RECUR_ADD = "A:RECUR_ADD"

    # pickers
    DONE_PICK = "DONE"  # f"DONE:{task_id}"
    DEL_PICK = "DEL"  # f"DEL:{task_id}"
    REM_PICK = "REM"  # f"REM:{task_id}"

    # reminder set
    RSET = "RSET"  # f"RSET:{task_id}:{kind}"

    # reminder message actions
    RM = "RM"  # f"RM:{action}:{task_id}"
    RM_ACK = "ACK"
    RM_S30 = "S30"


def cb_done(task_id: int) -> str:
    return f"{CB.DONE_PICK}:{task_id}"


def cb_del(task_id: int) -> str:
    return f"{CB.DEL_PICK}:{task_id}"


def cb_rem(task_id: int) -> str:
    return f"{CB.REM_PICK}:{task_id}"


def cb_rset(task_id: int, kind: str) -> str:
    return f"{CB.RSET}:{task_id}:{kind}"


def cb_rm_ack(task_id: int) -> str:
    return f"{CB.RM}:{CB.RM_ACK}:{task_id}"


def cb_rm_snooze30(task_id: int) -> str:
    return f"{CB.RM}:{CB.RM_S30}:{task_id}"


def cb_recur_del(rec_id: int) -> str:
    return f"RECUR_DEL:{rec_id}"


def cb_recur_sched(kind: str, day: int, month: Optional[int] = None) -> str:
    if kind == "Y" and month is not None:
        return f"RSCHED:Y:{day}:{month}"
    return f"RSCHED:M:{day}"
class ParsedCallback:
    """Результат разбора callback_data.

    type:
      - 'REMINDER_MSG'   — действия из сообщения-напоминания (RM:...)
      - 'PANEL'          — действия панели (A:LIST/CB.LIST и т.п.)
      - 'PICK_DONE'      — выбор задачи для DONE
      - 'PICK_DEL'       — выбор задачи для DEL
      - 'PICK_REM'       — выбор задачи для REM
      - 'RSET'           — изменение настроек напоминания
      - 'UNKNOWN'        — нераспознанный формат
    """

    type: str
    raw: str
    action: Optional[str] = None
    task_id: Optional[int] = None


def parse_callback(data: str) -> ParsedCallback:
    """
    Централизованный парсер callback_data.

    Поддерживает как текущий формат на базе CB.*, так и старые строки:
    - "RM:ACK:123", "RM:S30:123"
    - "A:LIST" и др.
    - "DONE:123", "DEL:123", "REM:123"
    - "RSET:123:KIND"
    """
    if not data:
        return ParsedCallback(type="UNKNOWN", raw=data or "")

    # reminder message actions: RM:ACK:task_id / RM:S30:task_id
    if data.startswith(f"{CB.RM}:") or data.startswith("RM:"):
        parts = data.split(":")
        if len(parts) == 3:
            _, action, task_id_str = parts
            try:
                task_id = int(task_id_str)
            except ValueError:
                task_id = None
            return ParsedCallback(
                type="REMINDER_MSG",
                raw=data,
                action=action,
                task_id=task_id,
            )
        return ParsedCallback(type="UNKNOWN", raw=data)

    # panel actions (LIST/ADD/DONE/DEL/REM/HIST/RECUR/RECUR_ADD)
    if data in {
        CB.LIST,
        CB.ADD,
        CB.DONE,
        CB.DEL,
        CB.REM,
        CB.HIST,
        CB.RECUR,
        CB.RECUR_ADD,
    }:
        return ParsedCallback(type="PANEL", raw=data, action=data)

    # pickers DONE/DEL/REM (CB-based и старый формат "DONE:123")
    if data.startswith(f"{CB.DONE_PICK}:") or data.startswith("DONE:"):
        _, task_id_str = data.split(":", 1)
        try:
            task_id = int(task_id_str)
        except ValueError:
            task_id = None
        return ParsedCallback(type="PICK_DONE", raw=data, task_id=task_id)

    if data.startswith(f"{CB.DEL_PICK}:") or data.startswith("DEL:"):
        _, task_id_str = data.split(":", 1)
        try:
            task_id = int(task_id_str)
        except ValueError:
            task_id = None
        return ParsedCallback(type="PICK_DEL", raw=data, task_id=task_id)

    # REM picker (исключая RM:... — они уже разобраны выше)
    if (data.startswith(f"{CB.REM_PICK}:") or data.startswith("REM:")) and not data.startswith("RM:"):
        _, task_id_str = data.split(":", 1)
        try:
            task_id = int(task_id_str)
        except ValueError:
            task_id = None
        return ParsedCallback(type="PICK_REM", raw=data, task_id=task_id)

    # RECUR_DEL:rec_id (task_id в ParsedCallback = rec_id)
    if data.startswith("RECUR_DEL:"):
        _, rec_id_str = data.split(":", 1)
        try:
            rec_id = int(rec_id_str)
        except ValueError:
            rec_id = None
        return ParsedCallback(type="RECUR_DEL", raw=data, task_id=rec_id)

    if data.startswith("RSCHED:"):
        parts = data.split(":")
        if len(parts) >= 3:
            action = ":".join(parts[1:])  # "M:5" or "Y:15:12"
            return ParsedCallback(type="RECUR_SCHED", raw=data, action=action)
        return ParsedCallback(type="UNKNOWN", raw=data)

    # reminder set: RSET:task_id:KIND
    if data.startswith(f"{CB.RSET}:") or data.startswith("RSET:"):
        parts = data.split(":")
        if len(parts) >= 3:
            _, task_id_str, kind = parts[0], parts[1], parts[2]
            try:
                task_id = int(task_id_str)
            except ValueError:
                task_id = None
            return ParsedCallback(
                type="RSET",
                raw=data,
                action=kind,
                task_id=task_id,
            )
        return ParsedCallback(type="UNKNOWN", raw=data)

    return ParsedCallback(type="UNKNOWN", raw=data)