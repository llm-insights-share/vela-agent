"""Playwright browser pool + live ScreenPilot sessions."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

logger = logging.getLogger(__name__)

_playwright = None
_local_browser = None
_cdp_browsers: Dict[str, Any] = {}
_cdp_launcher_procs: Dict[str, subprocess.Popen] = {}
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


def _auto_start_cdp_enabled() -> bool:
    raw = (os.getenv("SCREENPILOT_AUTO_START_CDP") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _cdp_port_from_endpoint(endpoint: str) -> int:
    try:
        parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
        if parsed.port:
            return int(parsed.port)
    except Exception:
        pass
    return 9222


def _cdp_user_data_dir(port: int) -> str:
    env = (os.getenv("SCREENPILOT_CDP_USER_DATA_DIR") or "").strip()
    if env:
        path = env
    else:
        try:
            from services.screenpilot.config import SCREENPILOT_DATA_DIR

            path = os.path.join(SCREENPILOT_DATA_DIR, f"chrome-cdp-{port}")
        except Exception:
            path = os.path.join("/tmp", f"vela-chrome-cdp-{port}")
    os.makedirs(path, exist_ok=True)
    return path


def _find_chrome_executable() -> str:
    env = (os.getenv("SCREENPILOT_CHROME_PATH") or "").strip()
    if env and os.path.isfile(env):
        return env

    system = platform.system()
    candidates: List[str] = []
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Windows":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            found = shutil.which(name)
            if found:
                return found
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise RuntimeError(
        "未找到 Chrome/Edge 可执行文件。请安装 Google Chrome，或设置环境变量 SCREENPILOT_CHROME_PATH。"
    )


def _is_cdp_refused(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "econnrefused",
            "connection refused",
            "err_connection_refused",
            "actively refused",
            "connect call failed",
            "could not connect",
        )
    )


async def _cdp_http_ready(endpoint: str, timeout_s: float = 1.5) -> bool:
    ep = (endpoint or "").rstrip("/")
    url = f"{ep}/json/version"

    def _probe() -> bool:
        try:
            with urlopen(url, timeout=timeout_s) as resp:
                return int(getattr(resp, "status", 200) or 200) < 500
        except Exception:
            return False

    return await asyncio.to_thread(_probe)


async def _ensure_cdp_chrome_launched(endpoint: str) -> Dict[str, Any]:
    """Start a dedicated Chrome/Edge with --remote-debugging-port if CDP is down."""
    ep = (endpoint or "").strip() or DEFAULT_CDP_URL
    if await _cdp_http_ready(ep):
        return {"launched": False, "already_ready": True, "cdp_url": ep}

    port = _cdp_port_from_endpoint(ep)
    chrome = _find_chrome_executable()
    user_data = _cdp_user_data_dir(port)
    proc = _cdp_launcher_procs.get(ep)
    if proc is not None and proc.poll() is None:
        # Already started by us; wait for readiness.
        pass
    else:
        args = [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "about:blank",
        ]
        logger.info("ScreenPilot auto-starting CDP browser: port=%s bin=%s", port, chrome)
        popen_kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if platform.system() != "Windows":
            popen_kwargs["start_new_session"] = True
        else:
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(args, **popen_kwargs)
        _cdp_launcher_procs[ep] = proc

    deadline = time.monotonic() + float(os.getenv("SCREENPILOT_CDP_START_TIMEOUT", "20") or "20")
    while time.monotonic() < deadline:
        if await _cdp_http_ready(ep, timeout_s=1.0):
            return {
                "launched": True,
                "already_ready": False,
                "cdp_url": ep,
                "pid": getattr(proc, "pid", None),
                "user_data_dir": user_data,
                "chrome_path": chrome,
            }
        if proc.poll() is not None:
            raise RuntimeError(
                f"自动启动的浏览器已退出（exit={proc.returncode}）。"
                f"请检查是否可执行：{chrome}，或端口 {port} 是否被占用。"
            )
        await asyncio.sleep(0.4)

    raise RuntimeError(
        f"已尝试自动启动浏览器，但 CDP 仍不可达（{ep}）。"
        f"请手动执行：\"{chrome}\" --remote-debugging-port={port} --user-data-dir=\"{user_data}\""
    )


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
    # Page ids present when the session bound its working page (CDP may share context).
    baseline_page_ids: set = field(default_factory=set)
    owned_page_ids: set = field(default_factory=set)


_sessions: Dict[str, LiveSession] = {}


def _page_url_safe(page: Any) -> str:
    try:
        return page.url or ""
    except Exception:
        return ""


async def adopt_spawned_pages(live: LiveSession) -> Dict[str, Any]:
    """If click/open spawned a child tab, switch live.page to the newest owned one.

    Prefers pages whose opener chain leads to the session page; for CDP sessions
    also adopts pages that appeared after session bind (not in baseline).
    """
    info: Dict[str, Any] = {"switched": False, "from_url": "", "to_url": "", "reason": ""}
    if getattr(live, "exec_mode", "browser") != "browser" or not live.page:
        return info
    ctx = live.context or getattr(live.page, "context", None)
    if not ctx:
        return info
    info["from_url"] = _page_url_safe(live.page)
    try:
        pages = [p for p in list(ctx.pages) if not p.is_closed()]
    except Exception as e:
        info["reason"] = f"list_pages_failed:{e}"
        return info

    owned = set(getattr(live, "owned_page_ids", None) or set())
    owned.add(id(live.page))
    baseline = set(getattr(live, "baseline_page_ids", None) or set())

    opener_hits: List[Any] = []
    baseline_hits: List[Any] = []
    for p in pages:
        pid = id(p)
        if pid in owned:
            continue
        url = _page_url_safe(p)
        opener = None
        try:
            opener = await p.opener()
        except Exception:
            opener = None
        hit_opener = False
        cur = opener
        seen: set = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if id(cur) in owned:
                hit_opener = True
                break
            try:
                cur = await cur.opener()
            except Exception:
                break
        if hit_opener:
            opener_hits.append(p)
            continue
        if baseline and pid not in baseline and url not in ("", "about:blank"):
            baseline_hits.append(p)

    candidates = opener_hits or baseline_hits
    if not candidates:
        info["reason"] = "no_spawned_page"
        info["page_count"] = len(pages)
        return info

    real = [p for p in candidates if _page_url_safe(p) not in ("", "about:blank")]
    chosen = (real or candidates)[-1]
    if chosen is live.page:
        info["reason"] = "already_on_spawned"
        return info

    live.page = chosen
    owned.add(id(chosen))
    live.owned_page_ids = owned
    info["switched"] = True
    info["to_url"] = _page_url_safe(chosen)
    info["reason"] = "opener" if chosen in opener_hits else "baseline_new"
    try:
        await chosen.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    return info


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


def _is_playwright_transport_closed(exc: BaseException) -> bool:
    msg = str(exc) or ""
    return (
        "WriteUnixTransport" in msg
        or "handler is closed" in msg
        or "Connection closed" in msg
        or "Target page, context or browser has been closed" in msg
    )


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


async def probe_live_session(sess: Optional[LiveSession]) -> bool:
    """True if the live page can still accept Playwright commands."""
    if not sess or sess.exec_mode == "desktop":
        return bool(sess)
    if not sess.page:
        return False
    try:
        if sess.page.is_closed():
            return False
        await sess.page.evaluate("() => true")
        return True
    except Exception as e:
        if _is_playwright_transport_closed(e):
            return False
        # Other transient evaluate errors: treat as usable if page not closed.
        try:
            return not sess.page.is_closed()
        except Exception:
            return False


async def discard_zombie_live_session(screen_session_id: str) -> None:
    """Drop in-memory live session without closing remote CDP tabs.

    Used when the Playwright driver transport died (e.g. after asyncio.run
    closed a temporary loop) but Chrome/CDP may still be running.
    """
    async with _lock:
        sess = _sessions.pop(screen_session_id, None)
        if not sess:
            await _reset_all_unlocked()
            return
        if sess.attach_mode == "cdp" or sess.owned_page_only:
            # Leave remote tabs open; only reset dead local driver refs.
            await _reset_all_unlocked()
            return
        try:
            await _close_session_resources(sess)
        except Exception:
            pass
        await _reset_all_unlocked()


async def _pick_cdp_page(context: Any, preferred_url: str = "") -> Any:
    try:
        pages = [p for p in list(context.pages or []) if not p.is_closed()]
    except Exception:
        pages = []
    pref = (preferred_url or "").strip()
    if pref and pages:
        for p in pages:
            url = _page_url_safe(p)
            if url and (url == pref or pref in url or url in pref):
                return p
    real = [p for p in pages if _page_url_safe(p) not in ("", "about:blank")]
    if real:
        return real[-1]
    if pages:
        return pages[-1]
    return await context.new_page()


async def _launch_chromium():
    pw = await _ensure_playwright()
    headless = os.getenv("SCREENPILOT_HEADLESS", "true").lower() in ("1", "true", "yes")
    return await pw.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )


async def _ensure_local_browser():
    global _local_browser
    if _local_browser is not None:
        try:
            if _local_browser.is_connected():
                return _local_browser
        except Exception:
            pass
        await _reset_local_browser_unlocked()

    try:
        _local_browser = await _launch_chromium()
    except Exception as e:
        if not _is_playwright_transport_closed(e):
            raise
        logger.warning(
            "Playwright driver transport closed; full reset and retry launch: %s",
            str(e)[:200],
        )
        await _reset_all_unlocked()
        _local_browser = await _launch_chromium()
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
    try:
        browser = await pw.chromium.connect_over_cdp(ep)
    except Exception as e:
        if not _is_playwright_transport_closed(e):
            raise
        logger.warning("CDP connect hit closed Playwright transport; resetting: %s", str(e)[:200])
        await _reset_all_unlocked()
        pw = await _ensure_playwright()
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
        hint = (
            "请先用远程调试端口启动 Chrome/Edge，例如：\n"
            '/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome '
            f'--remote-debugging-port=9222 --user-data-dir="/tmp/chrome-cdp"'
        )
        if _auto_start_cdp_enabled() and _is_cdp_refused(e):
            try:
                auto_info = await _ensure_cdp_chrome_launched(ep)
                browser = await _playwright.chromium.connect_over_cdp(ep)
                try:
                    return {
                        "connected": True,
                        "cdp_url": ep,
                        "auto_started": True,
                        "browser_version": getattr(browser, "version", "") or "",
                        "user_data_dir": auto_info.get("user_data_dir"),
                        "contexts": len(list(browser.contexts or [])),
                        "pages": sum(len(ctx.pages or []) for ctx in (browser.contexts or [])),
                    }
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
            except Exception as e2:
                return {
                    "connected": False,
                    "cdp_url": ep,
                    "error": str(e2)[:300],
                    "hint": hint,
                    "auto_start_attempted": True,
                }
        return {
            "connected": False,
            "cdp_url": ep,
            "error": str(e)[:300],
            "hint": hint,
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
    prefer_existing_page: bool = False,
    preferred_url: str = "",
) -> LiveSession:
    async with _lock:
        existing = _sessions.get(screen_session_id)
        if existing and _session_alive(existing):
            existing.last_activity_at = time.monotonic()
            return existing
        if existing:
            _sessions.pop(screen_session_id, None)
            # CDP revive: do not close remote tabs; drop dead driver instead.
            if prefer_existing_page and (
                existing.attach_mode == "cdp" or existing.owned_page_only
            ):
                try:
                    await _reset_all_unlocked()
                except Exception:
                    pass
            else:
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
                if _auto_start_cdp_enabled() and _is_cdp_refused(e):
                    try:
                        await _ensure_cdp_chrome_launched(endpoint)
                        browser = await _ensure_cdp_browser(endpoint)
                    except Exception as e2:
                        raise RuntimeError(
                            f"无法连接本地浏览器 CDP ({endpoint}): {e2}. "
                            "已尝试自动启动 Chrome/Edge 仍失败。"
                            "可设置 SCREENPILOT_CHROME_PATH，或手动以 "
                            "--remote-debugging-port 启动浏览器。"
                        ) from e2
                else:
                    raise RuntimeError(
                        f"无法连接本地浏览器 CDP ({endpoint}): {e}. "
                        "请先以 --remote-debugging-port 启动 Chrome/Edge 并保持已登录状态。"
                        "（也可开启自动启动：SCREENPILOT_AUTO_START_CDP=true）"
                    ) from e
            contexts = list(browser.contexts or [])
            if not contexts:
                raise RuntimeError(
                    f"CDP 浏览器无可用 context（{endpoint}）。"
                    "请确认已用远程调试模式启动并至少打开一个窗口。"
                )
            # Reuse default profile context — do NOT new_context() (isolated, no cookies).
            context = contexts[0]
            if prefer_existing_page:
                page = await _pick_cdp_page(context, preferred_url=preferred_url)
            else:
                page = await context.new_page()
            baseline_ids = set()
            try:
                baseline_ids = {id(p) for p in list(context.pages)}
            except Exception:
                baseline_ids = {id(page)}
            sess = LiveSession(
                screen_session_id=screen_session_id,
                system_id=system_id,
                context=context,
                page=page,
                exec_mode="browser",
                attach_mode="cdp",
                owned_page_only=True,
                cdp_endpoint=endpoint,
                baseline_page_ids=baseline_ids,
                owned_page_ids={id(page)},
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
        except Exception as e:
            # Browser object may be stale; reset driver if transport died.
            if _is_playwright_transport_closed(e):
                await _reset_all_unlocked()
            else:
                await _reset_local_browser_unlocked()
            browser = await _ensure_local_browser()
            context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()
        baseline_ids = set()
        try:
            baseline_ids = {id(p) for p in list(context.pages)}
        except Exception:
            baseline_ids = {id(page)}
        sess = LiveSession(
            screen_session_id=screen_session_id,
            system_id=system_id,
            context=context,
            page=page,
            exec_mode="browser",
            attach_mode="launch",
            owned_page_only=False,
            baseline_page_ids=baseline_ids,
            owned_page_ids={id(page)},
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
