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
_local_browser = None
_cdp_browsers: Dict[str, Any] = {}
_lock = asyncio.Lock()
_reaper_task: Optional[asyncio.Task] = None

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


def _inactivity_timeout_seconds() -> float:
    raw = os.getenv("SCREENPILOT_INACTIVITY_TIMEOUT", "300").strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 300.0


def resolve_cdp_endpoint(cdp_url: str = "") -> str:
    """Resolve CDP URL: per-system > env > vela.yaml > default localhost:9222."""
    raw = (cdp_url or "").strip()
    if raw:
        return raw
    env = (os.getenv("SCREENPILOT_CDP_URL") or "").strip()
    if env:
        return env
    try:
        from services.screenpilot.config import _load_vela_yaml

        sp = (_load_vela_yaml() or {}).get("screenpilot") or {}
        if isinstance(sp, dict):
            yaml_url = (sp.get("cdp_url") or "").strip()
            if yaml_url:
                return yaml_url
    except Exception:
        pass
    return DEFAULT_CDP_URL


def _cdp_url() -> str:
    """Legacy global CDP env (empty means do not force global CDP for launch)."""
    return (os.getenv("SCREENPILOT_CDP_URL") or "").strip()


@dataclass
class LiveSession:
    screen_session_id: str
    system_id: str
    context: Any
    page: Any
    exec_mode: str = "browser"
    attach_mode: str = "launch"  # launch | cdp
    owned_page_only: bool = False
    cdp_endpoint: str = ""
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


async def _ensure_playwright():
    global _playwright
    if _playwright is None:
        from playwright.async_api import async_playwright

        _playwright = await async_playwright().start()
    return _playwright


async def _reset_local_browser_unlocked() -> None:
    global _local_browser
    if _local_browser:
        try:
            await _local_browser.close()
        except Exception:
            pass
        _local_browser = None


async def _disconnect_cdp_unlocked(endpoint: Optional[str] = None) -> None:
    global _cdp_browsers
    if endpoint:
        browser = _cdp_browsers.pop(endpoint, None)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        return
    for url, browser in list(_cdp_browsers.items()):
        try:
            await browser.close()
        except Exception:
            pass
        _cdp_browsers.pop(url, None)


async def _reset_all_unlocked() -> None:
    global _playwright
    await _reset_local_browser_unlocked()
    await _disconnect_cdp_unlocked()
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


async def _ensure_local_browser():
    global _local_browser
    if _local_browser is not None:
        try:
            if _local_browser.is_connected():
                return _local_browser
        except Exception:
            pass
        await _reset_local_browser_unlocked()

    pw = await _ensure_playwright()
    headless = os.getenv("SCREENPILOT_HEADLESS", "true").lower() in ("1", "true", "yes")
    _local_browser = await pw.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    return _local_browser


async def _ensure_cdp_browser(endpoint: str):
    global _cdp_browsers
    ep = (endpoint or "").strip() or DEFAULT_CDP_URL
    browser = _cdp_browsers.get(ep)
    if browser is not None:
        try:
            if browser.is_connected():
                return browser
        except Exception:
            pass
        await _disconnect_cdp_unlocked(ep)

    pw = await _ensure_playwright()
    logger.info("ScreenPilot attaching Chromium via CDP: %s", ep)
    browser = await pw.chromium.connect_over_cdp(ep)
    _cdp_browsers[ep] = browser
    return browser


async def probe_cdp(endpoint: str = "") -> Dict[str, Any]:
    """Connect briefly and report CDP browser status (does not leave session pages)."""
    ep = resolve_cdp_endpoint(endpoint)
    try:
        global _playwright
        if _playwright is None:
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
        browser = await _playwright.chromium.connect_over_cdp(ep)
        try:
            version = ""
            try:
                version = browser.version
            except Exception:
                version = ""
            contexts = list(browser.contexts or [])
            page_count = 0
            for ctx in contexts:
                try:
                    page_count += len(ctx.pages or [])
                except Exception:
                    pass
            return {
                "connected": True,
                "cdp_url": ep,
                "browser_version": version or "",
                "contexts": len(contexts),
                "pages": page_count,
            }
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    except Exception as e:
        return {
            "connected": False,
            "cdp_url": ep,
            "error": str(e)[:300],
            "hint": (
                "请先用远程调试端口启动 Chrome/Edge，例如：\n"
                '/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome '
                f'--remote-debugging-port=9222 --user-data-dir="/tmp/chrome-cdp"'
            ),
        }


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


async def _close_session_resources(sess: LiveSession) -> None:
    """Close only what we own. CDP: page only. Launch: whole context."""
    if sess.owned_page_only or sess.attach_mode == "cdp":
        if sess.page:
            try:
                if not sess.page.is_closed():
                    await sess.page.close()
            except Exception:
                pass
        return
    if sess.context:
        try:
            await sess.context.close()
        except Exception:
            pass


async def create_live_session(
    screen_session_id: str,
    system_id: str,
    *,
    exec_mode: str = "browser",
    desktop_macro: Optional[Dict[str, Any]] = None,
    storage_state: Optional[Dict[str, Any]] = None,
    reuse_local_browser: bool = False,
    cdp_url: str = "",
) -> LiveSession:
    async with _lock:
        existing = _sessions.get(screen_session_id)
        if existing and _session_alive(existing):
            existing.last_activity_at = time.monotonic()
            return existing
        if existing:
            _sessions.pop(screen_session_id, None)
            await _close_session_resources(existing)

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

        if reuse_local_browser:
            endpoint = resolve_cdp_endpoint(cdp_url)
            try:
                browser = await _ensure_cdp_browser(endpoint)
            except Exception as e:
                raise RuntimeError(
                    f"无法连接本地浏览器 CDP ({endpoint}): {e}. "
                    "请先以 --remote-debugging-port 启动 Chrome/Edge 并保持已登录状态。"
                ) from e
            contexts = list(browser.contexts or [])
            if not contexts:
                raise RuntimeError(
                    f"CDP 浏览器无可用 context（{endpoint}）。"
                    "请确认已用远程调试模式启动并至少打开一个窗口。"
                )
            # Reuse default profile context — do NOT new_context() (isolated, no cookies).
            context = contexts[0]
            page = await context.new_page()
            sess = LiveSession(
                screen_session_id=screen_session_id,
                system_id=system_id,
                context=context,
                page=page,
                exec_mode="browser",
                attach_mode="cdp",
                owned_page_only=True,
                cdp_endpoint=endpoint,
            )
            _sessions[screen_session_id] = sess
            await _ensure_reaper_unlocked()
            return sess

        browser = await _ensure_local_browser()
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
            await _reset_local_browser_unlocked()
            browser = await _ensure_local_browser()
            context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()
        sess = LiveSession(
            screen_session_id=screen_session_id,
            system_id=system_id,
            context=context,
            page=page,
            exec_mode="browser",
            attach_mode="launch",
            owned_page_only=False,
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
        if not sess:
            return
        await _close_session_resources(sess)


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
            if sess:
                await _close_session_resources(sess)
        await _reset_all_unlocked()


def is_cdp_mode() -> bool:
    """True if any CDP browser connection is active."""
    return bool(_cdp_browsers)
