"""Тесты протокола callback_data и прав."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from taskbot.callbacks import parse_callback, CB, cb_done, cb_del, cb_rem, cb_rset
from taskbot.permissions import is_group, can_action


# --- callbacks ---


def test_parse_callback_reminder_msg():
    p = parse_callback("RM:ACK:42")
    assert p.type == "REMINDER_MSG"
    assert p.action == "ACK"
    assert p.task_id == 42

    p = parse_callback("RM:S30:1")
    assert p.type == "REMINDER_MSG"
    assert p.action == "S30"
    assert p.task_id == 1


def test_parse_callback_panel():
    for data in (CB.LIST, CB.ADD, CB.DONE, CB.HIST):
        p = parse_callback(data)
        assert p.type == "PANEL"
        assert p.action == data


def test_parse_callback_pickers():
    p = parse_callback("DONE:10")
    assert p.type == "PICK_DONE"
    assert p.task_id == 10

    p = parse_callback("DEL:5")
    assert p.type == "PICK_DEL"
    assert p.task_id == 5

    p = parse_callback("REM:7")
    assert p.type == "PICK_REM"
    assert p.task_id == 7


def test_parse_callback_rset():
    p = parse_callback("RSET:3:30M")
    assert p.type == "RSET"
    assert p.task_id == 3
    assert p.action == "30M"


def test_cb_helpers():
    assert cb_done(1) == "DONE:1"
    assert cb_del(2) == "DEL:2"
    assert cb_rem(3) == "REM:3"
    assert cb_rset(4, "NONE") == "RSET:4:NONE"


# --- permissions (sync) ---


def test_is_group():
    chat = MagicMock()
    chat.type = "group"
    assert is_group(chat) is True
    chat.type = "supergroup"
    assert is_group(chat) is True
    chat.type = "private"
    assert is_group(chat) is False


# --- permissions (async) ---


@pytest.mark.asyncio
async def test_can_action_private_allows_all():
    chat = MagicMock()
    chat.type = "private"
    chat.id = 1
    # context не используется для private
    context = MagicMock()
    assert await can_action(context=context, chat=chat, actor_id=100, action="DELETE", task_owner_id=999) is True
    assert await can_action(context=context, chat=chat, actor_id=100, action="REM", task_owner_id=999) is True


@pytest.mark.asyncio
async def test_can_action_group_allow_add_done_list_hist():
    chat = MagicMock()
    chat.type = "group"
    chat.id = 1
    context = MagicMock()
    for action in ("ADD", "DONE", "LIST", "HIST"):
        assert await can_action(context=context, chat=chat, actor_id=100, action=action, task_owner_id=None) is True


@pytest.mark.asyncio
async def test_can_action_group_rem_as_author():
    chat = MagicMock()
    chat.type = "group"
    chat.id = 1
    context = MagicMock()
    assert await can_action(context=context, chat=chat, actor_id=100, action="REM", task_owner_id=100) is True


@pytest.mark.asyncio
async def test_can_action_group_delete_as_author():
    chat = MagicMock()
    chat.type = "group"
    chat.id = 1
    context = MagicMock()
    assert await can_action(context=context, chat=chat, actor_id=100, action="DELETE", task_owner_id=100) is True


@pytest.mark.asyncio
async def test_can_action_group_rem_not_author_calls_is_admin():
    chat = MagicMock()
    chat.type = "group"
    chat.id = 1
    context = AsyncMock()
    context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator"))
    assert await can_action(context=context, chat=chat, actor_id=200, action="REM", task_owner_id=100) is True
    context.bot.get_chat_member.assert_called_once_with(1, 200)


@pytest.mark.asyncio
async def test_can_action_group_rem_not_author_not_admin():
    chat = MagicMock()
    chat.type = "group"
    chat.id = 1
    context = AsyncMock()
    context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
    assert await can_action(context=context, chat=chat, actor_id=200, action="REM", task_owner_id=100) is False
