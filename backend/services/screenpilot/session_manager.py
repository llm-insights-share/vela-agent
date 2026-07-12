import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_playwright = None
_browser = None
_lock = asyncio.Lock()


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


_sessions: Dict[str, LiveSession] = {}


async def _ensure_browser():
    global _playwright, _browser
    if _browser is not None:
        return _browser
    from playwright.async_api import async_playwright

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True)
    return _browser


async def create_live_session(
    screen_session_id: str,
    system_id: str,
    *,
    exec_mode: str = "browser",
    desktop_macro: Optional[Dict[str, Any]] = None,
) -> LiveSession:
    async with _lock:
        if screen_session_id in _sessions:
            return _sessions[screen_session_id]

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
            return sess

        browser = await _ensure_browser()
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        sess = LiveSession(
            screen_session_id=screen_session_id,
            system_id=system_id,
            context=context,
            page=page,
            exec_mode="browser",
        )
        _sessions[screen_session_id] = sess
        return sess


def get_live_session(screen_session_id: str) -> Optional[LiveSession]:
    return _sessions.get(screen_session_id)


async def close_live_session(screen_session_id: str) -> None:
    async with _lock:
        sess = _sessions.pop(screen_session_id, None)
        if not sess:
            return
        try:
            await sess.context.close()
        except Exception:
            pass


async def shutdown_browser_pool() -> None:
    global _playwright, _browser
    async with _lock:
        for sid in list(_sessions.keys()):
            await close_live_session(sid)
        if _browser:
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None
