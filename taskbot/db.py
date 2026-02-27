from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from .config import DB_PATH, TZ


# ---------- connection + session ----------
def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row

    # Pragmas for better stability under concurrent reads/writes
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """
    Safe DB session:
    - commit on success
    - rollback on exception
    - always closes
    """
    conn = db_connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- migrations helpers ----------
def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall()
    return {r["name"] for r in rows}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, col_def: str):
    cols = _table_columns(conn, table)
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")


def db_init():
    with db_session() as conn:
        cur = conn.cursor()

        # Base tables
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                remind_at TEXT,
                reminded INTEGER NOT NULL DEFAULT 0,
                deleted INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id INTEGER PRIMARY KEY,
                panel_message_id INTEGER
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                task_id INTEGER,
                created_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )

        # --- migrations for v2 ---
        _add_column_if_missing(conn, "tasks", "owner_id", "INTEGER")
        _add_column_if_missing(conn, "tasks", "owner_name", "TEXT")
        _add_column_if_missing(conn, "tasks", "done_by_id", "INTEGER")
        _add_column_if_missing(conn, "tasks", "done_by_name", "TEXT")
        _add_column_if_missing(conn, "tasks", "done_at", "TEXT")
        _add_column_if_missing(conn, "tasks", "reminder_message_id", "INTEGER")

        # audit log
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                actor_name TEXT,
                action TEXT NOT NULL,
                task_id INTEGER,
                meta TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        # indices
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_chat_deleted_id ON tasks(chat_id, deleted, id DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_remind ON tasks(deleted, done, reminded, remind_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pending_chat_user ON pending(chat_id, user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_chat_time ON audit_log(chat_id, id DESC)")

        # recurring reminders
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS recurring_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                repeat_kind TEXT NOT NULL,
                day_of_month INTEGER NOT NULL,
                month INTEGER,
                hour INTEGER NOT NULL DEFAULT 10,
                minute INTEGER NOT NULL DEFAULT 0,
                next_run_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                owner_id INTEGER,
                owner_name TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_recurring_next ON recurring_reminders(next_run_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_recurring_chat ON recurring_reminders(chat_id)")

        _add_column_if_missing(conn, "pending", "meta", "TEXT")


# ---------- chat_state ----------
def set_panel_message_id(chat_id: int, message_id: Optional[int]):
    with db_session() as conn:
        conn.execute(
            "INSERT INTO chat_state(chat_id, panel_message_id) VALUES(?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET panel_message_id=excluded.panel_message_id",
            (chat_id, message_id),
        )


def get_panel_message_id(chat_id: int) -> Optional[int]:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("SELECT panel_message_id FROM chat_state WHERE chat_id=?", (chat_id,))
        row = cur.fetchone()
        return row["panel_message_id"] if row else None


# ---------- pending ----------
def pending_set(chat_id: int, user_id: int, action: str, task_id: Optional[int] = None, meta: Optional[str] = None):
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO pending(chat_id, user_id, action, task_id, meta, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                action=excluded.action,
                task_id=excluded.task_id,
                meta=excluded.meta,
                created_at=excluded.created_at
            """,
            (chat_id, user_id, action, task_id, meta, datetime.now(TZ).isoformat()),
        )


def pending_get(chat_id: int, user_id: int):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT chat_id, user_id, action, task_id, meta FROM pending WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        )
        return cur.fetchone()


def pending_clear(chat_id: int, user_id: int):
    with db_session() as conn:
        conn.execute("DELETE FROM pending WHERE chat_id=? AND user_id=?", (chat_id, user_id))


# ---------- tasks ----------
def insert_task(chat_id: int, owner_id: int, owner_name: str, text: str) -> int:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks(chat_id, text, done, created_at, reminded, deleted, owner_id, owner_name)
            VALUES(?, ?, 0, ?, 0, 0, ?, ?)
            """,
            (chat_id, text, datetime.now(TZ).isoformat(), owner_id, owner_name),
        )
        return int(cur.lastrowid)


def fetch_tasks(chat_id: int, limit: int = 20):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, text, done, remind_at, reminded, owner_id, owner_name, reminder_message_id, deleted
            FROM tasks
            WHERE chat_id=? AND deleted=0
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        return cur.fetchall()


def fetch_open_tasks(chat_id: int, limit: int = 10):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, text, remind_at, reminded, owner_id, owner_name, reminder_message_id
            FROM tasks
            WHERE chat_id=? AND deleted=0 AND done=0
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        return cur.fetchall()


def fetch_task(chat_id: int, task_id: int):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM tasks
            WHERE chat_id=? AND id=?
            """,
            (chat_id, task_id),
        )
        return cur.fetchone()


def set_task_remind(chat_id: int, task_id: int, remind_at_iso: Optional[str]):
    with db_session() as conn:
        conn.execute(
            "UPDATE tasks SET remind_at=?, reminded=0 WHERE chat_id=? AND id=? AND deleted=0",
            (remind_at_iso, chat_id, task_id),
        )


def set_task_reminder_message_id(chat_id: int, task_id: int, message_id: Optional[int]):
    with db_session() as conn:
        conn.execute(
            "UPDATE tasks SET reminder_message_id=? WHERE chat_id=? AND id=?",
            (message_id, chat_id, task_id),
        )


def mark_done(chat_id: int, task_id: int, done_by_id: int, done_by_name: str) -> bool:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE tasks
            SET done=1,
                done_by_id=?,
                done_by_name=?,
                done_at=?
            WHERE chat_id=? AND id=? AND deleted=0 AND done=0
            """,
            (done_by_id, done_by_name, datetime.now(TZ).isoformat(), chat_id, task_id),
        )
        return cur.rowcount > 0


def soft_delete(chat_id: int, task_id: int) -> bool:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tasks SET deleted=1 WHERE chat_id=? AND id=? AND deleted=0",
            (chat_id, task_id),
        )
        return cur.rowcount > 0


def mark_reminded(chat_id: int, task_id: int):
    with db_session() as conn:
        conn.execute("UPDATE tasks SET reminded=1 WHERE chat_id=? AND id=?", (chat_id, task_id))


def fetch_pending_reminders():
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT chat_id, id AS task_id, remind_at
            FROM tasks
            WHERE deleted=0 AND done=0 AND reminded=0 AND remind_at IS NOT NULL
            """
        )
        return cur.fetchall()


# ---------- audit log ----------
def audit_insert(chat_id: int, actor_id: int, actor_name: str, action: str, task_id: Optional[int], meta: Optional[str]):
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO audit_log(chat_id, actor_id, actor_name, action, task_id, meta, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, actor_id, actor_name, action, task_id, meta, datetime.now(TZ).isoformat()),
        )


def audit_fetch(chat_id: int, limit: int = 50):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, actor_id, actor_name, action, task_id, meta, created_at
            FROM audit_log
            WHERE chat_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        return cur.fetchall()


def fetch_task_text(chat_id: int, task_id: int) -> Optional[str]:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT text FROM tasks WHERE chat_id=? AND id=?",
            (chat_id, task_id),
        )
        row = cur.fetchone()
        return row["text"] if row else None


# ---------- recurring_reminders ----------
def recurring_insert(
    chat_id: int,
    owner_id: int,
    owner_name: str,
    text: str,
    repeat_kind: str,
    day_of_month: int,
    next_run_at_iso: str,
    month: Optional[int] = None,
    hour: int = 10,
    minute: int = 0,
) -> int:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO recurring_reminders (
                chat_id, text, repeat_kind, day_of_month, month, hour, minute,
                next_run_at, created_at, owner_id, owner_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                text,
                repeat_kind,
                day_of_month,
                month,
                hour,
                minute,
                next_run_at_iso,
                datetime.now(TZ).isoformat(),
                owner_id,
                owner_name,
            ),
        )
        return int(cur.lastrowid)


def recurring_fetch_by_chat(chat_id: int):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, text, repeat_kind, day_of_month, month, hour, minute, next_run_at, created_at
            FROM recurring_reminders
            WHERE chat_id=?
            ORDER BY next_run_at ASC
            """,
            (chat_id,),
        )
        return cur.fetchall()


def recurring_fetch_one(chat_id: int, rec_id: int):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM recurring_reminders WHERE chat_id=? AND id=?",
            (chat_id, rec_id),
        )
        return cur.fetchone()


def recurring_update_next_run(rec_id: int, next_run_at_iso: str) -> bool:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE recurring_reminders SET next_run_at=? WHERE id=?",
            (next_run_at_iso, rec_id),
        )
        return cur.rowcount > 0


def recurring_delete(chat_id: int, rec_id: int) -> bool:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM recurring_reminders WHERE chat_id=? AND id=?", (chat_id, rec_id))
        return cur.rowcount > 0


def recurring_fetch_due(now_iso: str):
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, chat_id, text, repeat_kind, day_of_month, month, hour, minute FROM recurring_reminders WHERE next_run_at <= ?",
            (now_iso,),
        )
        return cur.fetchall()
