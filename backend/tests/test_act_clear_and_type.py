"""Tests for type-into-field clearing browser prefills."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.screenpilot.layers.act import clear_and_type


@pytest.mark.asyncio
async def test_clear_and_type_selects_then_backspaces_then_types():
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.type = AsyncMock()

    await clear_and_type(page, "zhangjr")

    assert page.keyboard.press.await_count == 2
    assert page.keyboard.press.await_args_list[0].args[0] == "ControlOrMeta+A"
    assert page.keyboard.press.await_args_list[1].args[0] == "Backspace"
    page.keyboard.type.assert_awaited_once_with("zhangjr")


@pytest.mark.asyncio
async def test_clear_and_type_empty_value_still_clears():
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.type = AsyncMock()

    await clear_and_type(page, None)

    assert page.keyboard.press.await_args_list[0].args[0] == "ControlOrMeta+A"
    assert page.keyboard.press.await_args_list[1].args[0] == "Backspace"
    page.keyboard.type.assert_awaited_once_with("")


@pytest.mark.asyncio
async def test_execute_action_type_uses_clear_and_type():
    from services.screenpilot.layers import act as act_mod

    page = MagicMock()
    page.url = "https://example.com/login"
    page.screenshot = AsyncMock(return_value=b"png")
    page.mouse = MagicMock()
    page.mouse.click = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.type = AsyncMock()

    elements = [
        {
            "ref": "[3]",
            "label": "请输入用户名",
            "role": "textbox",
            "box": {"x": 10, "y": 10, "width": 100, "height": 20},
            "box_css": {"x": 10, "y": 10, "width": 100, "height": 20},
        }
    ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            act_mod,
            "verify_action",
            AsyncMock(return_value={"ok": True, "effect_ok": True}),
        )
        mp.setattr(
            act_mod,
            "snapshot_target_state",
            AsyncMock(return_value=None),
        )
        result = await act_mod.execute_action(
            page,
            "type",
            elements,
            target_ref="[3]",
            value="zhangjr",
        )

    assert result.get("success") is True
    assert page.keyboard.press.await_args_list[0].args[0] == "ControlOrMeta+A"
    assert page.keyboard.press.await_args_list[1].args[0] == "Backspace"
    page.keyboard.type.assert_awaited_once_with("zhangjr")
