"""FR-MTG-09: guest mode uses no persistent profile; all browser calls are fake."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.browser import MeetBrowser, NotLoggedIn


def fake_runtime(monkeypatch, tmp_path, *, guest):
    page = SimpleNamespace()
    context = SimpleNamespace(pages=[page], close=AsyncMock())
    chromium_browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    chromium = SimpleNamespace(
        launch=AsyncMock(return_value=chromium_browser),
        launch_persistent_context=AsyncMock(return_value=context),
    )
    runtime = SimpleNamespace(chromium=chromium, stop=AsyncMock())
    manager = SimpleNamespace(start=AsyncMock(return_value=runtime))
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "playwright.async_api", SimpleNamespace(async_playwright=lambda: manager))
    cfg = SimpleNamespace(
        guest=guest,
        profile_dir=tmp_path / "forbidden-profile",
        debug_dir=tmp_path,
        bot_email="",
        bot_display_name="Tilo notetaker",
    )
    return MeetBrowser(cfg), chromium, chromium_browser, context, runtime


def test_FR_MTG_09_guest_uses_ephemeral_context_and_closes_browser(monkeypatch, tmp_path):
    bot, chromium, browser, context, runtime = fake_runtime(monkeypatch, tmp_path, guest=True)

    async def run():
        async with bot:
            assert bot.page is context.pages[0]

    asyncio.run(run())
    chromium.launch_persistent_context.assert_not_awaited()
    assert not (tmp_path / "forbidden-profile").exists()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    runtime.stop.assert_awaited_once()


def test_FR_MTG_09_cloud_refuses_signed_in_profile_before_browser_start(monkeypatch, tmp_path):
    bot, chromium, browser, context, runtime = fake_runtime(monkeypatch, tmp_path, guest=False)
    monkeypatch.setenv("K_SERVICE", "tilo-meet-bot")
    with pytest.raises(NotLoggedIn):
        asyncio.run(bot.__aenter__())
    chromium.launch_persistent_context.assert_not_awaited()
    chromium.launch.assert_not_awaited()


@pytest.mark.parametrize("account_present", [True, False])
def test_FR_MTG_09_guest_never_uses_a_signed_in_account(monkeypatch, tmp_path, account_present):
    bot, *_ = fake_runtime(monkeypatch, tmp_path, guest=True)
    bot.find = AsyncMock(return_value=object() if account_present else None)
    if account_present:
        with pytest.raises(NotLoggedIn):
            asyncio.run(bot.check_account())
    else:
        asyncio.run(bot.check_account())


def test_FR_MTG_09_guest_sets_its_display_name_before_asking_for_admission(monkeypatch, tmp_path):
    from bot import selectors as S

    bot, *_ = fake_runtime(monkeypatch, tmp_path, guest=True)
    bot.cfg.join_timeout_s = 1
    name = SimpleNamespace(fill=AsyncMock())
    bot.find = AsyncMock(return_value=name)
    bot.check_account, bot._wait_in_call = AsyncMock(), AsyncMock()
    bot._check_url_login = lambda: None

    async def visible(selector):
        return selector == S.ASK_TO_JOIN

    async def click(selector, **kwargs):
        return selector == S.ASK_TO_JOIN

    bot.visible, bot.click = visible, click
    assert asyncio.run(bot.join()) is True
    assert name.fill.await_args.args == ("Tilo notetaker",)
    bot._wait_in_call.assert_awaited_once_with(True)
