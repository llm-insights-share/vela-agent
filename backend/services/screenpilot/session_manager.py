"""Playwright browser pool + live ScreenPilot sessions."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_playwright = None
_browser = None
_cdp_mode = False
_lock = asyncio.Lock()
_reaper_task: Optional[asyncio.Task] = None


def _inactivity_timeout_seconds() -> float:
    raw = os.getenv("SCREENPILOT_INACTIVITY_TIMEOUT", "300").strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 300.0


def _cdp_url() -> str:
    return (os.getenv("SCREENPILOT_CDP_URL") or "").strip()


@dataclass
class LiveSession:
    screen_session_id: str
    system_id: str
    context: Any
    page: Any
    exec_mode: str = "browser"
    desktop_macro: Dict[str, Any] = field(default_factory=dict)
    elements: List[Dict[str, Any]] = field(default_factory=list)
    last_screenshot: bytes = b""
    last_som_image: bytes = b""
    last_activity_at: float = field(default_factory=time.monotonic)


_sessions: Dict[str, LiveSession] = {}


def touch_session(screen_session_id: str) -> None:
    sess = _sessions.get(screen_session_id)
    if sess:
        sess.last_activity_at = time.monotonic()


async def _reset_browser_unlocked() -> None:
    global _playwright, _browser, _cdp_mode
    if _browser:
        try:
            # CDP attach: disconnect Playwright client; leave user Chrome running.
            await _browser.close()
        except Exception:
            pass
        _browser = None
    _cdp_mode = False
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None


def _session_alive(sess: LiveSession) -> bool:
    if sess.exec_mode == "desktop":
        return True
    try:
        return bool(sess.page and not sess.page.is_closed())
    except Exception:
        return False


async def _ensure_browser():
    global _playwright, _browser, _cdp_mode
    if _browser is not None:
        try:
            if _browser.is_connected():
                return _browser
        except Exception:
            pass
        await _reset_browser_unlocked()

    from playwright.async_api import async_playwright

    _playwright = await async_playwright().start()
    cdp = _cdp_url()
    if cdp:
        logger.info("ScreenPilot attaching Chromium via CDP: %s", cdp)
        _browser = await _playwright.chromium.connect_over_cdp(cdp)
        _cdp_mode = True
    else:
        headless = os.getenv("SCREENPILOT_HEADLESS", "true").lower() in ("1", "true", "yes")
        _browser = await _playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        _cdp_mode = False
    return _browser


async def _ensure_reaper_unlocked() -> None:
    global _reaper_task
    if _reaper_task is not None and not _reaper_task.done():
        return
    _reaper_task = asyncio.create_task(_idle_reaper_loop(), name="screenpilot-idle-reaper")


async def _idle_reaper_loop() -> None:
    while True:
        try:
            await asyncio.sleep(30)
            timeout = _inactivity_timeout_seconds()
            now = time.monotonic()
            stale: List[str] = []
            async with _lock:
                for sid, sess in list(_sessions.items()):
                    if now - sess.last_activity_at >= timeout:
                        stale.append(sid)
            for sid in stale:
                logger.info("Closing idle ScreenPilot session %s", sid)
                await close_live_session(sid)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("ScreenPilot idle reaper error: %s", exc)


async def create_live_session(
    screen_session_id: str,
    system_id: str,
    *,
    exec_mode: str = "browser",
    desktop_macro: Optional[Dict[str, Any]] = None,
    storage_state: Optional[Dict[str, Any]] = None,
) -> LiveSession:
    async with _lock:
        existing = _sessions.get(screen_session_id)
        if existing and _session_alive(existing):
            existing.last_activity_at = time.monotonic()
            return existing
        if existing:
            _sessions.pop(screen_session_id, None)
            try:
                if existing.context:
                    await existing.context.close()
            except Exception:
                pass

        mode = (exec_mode or "browser").lower()
        if mode == "desktop":
            sess = LiveSession(
                screen_session_id=screen_session_id,
                system_id=system_id,
                context=None,
                page=None,
                exec_mode="desktop",
                desktop_macro=desktop_macro or {},
            )
            _sessions[screen_session_id] = sess
            await _ensure_reaper_unlocked()
            return sess

        browser = await _ensure_browser()
        ctx_kwargs: Dict[str, Any] = {
            "viewport": {"width": 1280, "height": 800},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        try:
            context = await browser.new_context(**ctx_kwargs)
        except Exception:
            await _reset_browser_unlocked()
            browser = await _ensure_browser()
            context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()
        sess = LiveSession(
            screen_session_id=screen_session_id,
            system_id=system_id,
            context=context,
            page=page,
            exec_mode="browser",
        )
        _sessions[screen_session_id] = sess
        await _ensure_reaper_unlocked()
        return sess


def get_live_session(screen_session_id: str) -> Optional[LiveSession]:
    sess = _sessions.get(screen_session_id)
    if sess:
        sess.last_activity_at = time.monotonic()
    return sess


async def close_live_session(screen_session_id: str) -> None:
    async with _lock:
        sess = _sessions.pop(screen_session_id, None)
        if not sess or not sess.context:
            return
        try:
            await sess.context.close()
        except Exception:
            pass


async def shutdown_browser_pool() -> None:
    global _reaper_task
    if _reaper_task is not None:
        _reaper_task.cancel()
        try:
            await _reaper_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        _reaper_task = None
    async with _lock:
        for sid in list(_sessions.keys()):
            sess = _sessions.pop(sid, None)
            if sess and sess.context:
                try:
                    await sess.context.close()
                except Exception:
                    pass
        await _reset_browser_unlocked()


def is_cdp_mode() -> bool:
    return _cdp_mode
