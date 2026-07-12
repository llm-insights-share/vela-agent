"""桌面模式 POC — Xvfb/DISPLAY 环境下截图 + 坐标点击（遗留 C/S）。"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def desktop_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _run_cmd(cmd: list, timeout: float = 10) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        return False, proc.stderr.strip() or proc.stdout.strip()
    except FileNotFoundError:
        return False, f"命令不存在: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def capture_screenshot_png() -> bytes:
    """捕获桌面截图；优先 scrot，其次 Pillow ImageGrab。"""
    if shutil.which("scrot"):
        path = "/tmp/screenpilot_desktop.png"
        ok, err = _run_cmd(["scrot", "-o", path])
        if ok and os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()

    if shutil.which("import"):  # ImageMagick
        path = "/tmp/screenpilot_desktop.png"
        ok, err = _run_cmd(["import", "-window", "root", path])
        if ok and os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()

    try:
        from PIL import ImageGrab

        if not desktop_available():
            raise RuntimeError("无 DISPLAY，无法截屏")
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        raise RuntimeError(f"桌面截图失败: {e}") from e


def parse_coord(value: str) -> Optional[Tuple[int, int]]:
    if not value:
        return None
    cleaned = value.strip().strip("[]")
    if "," in cleaned:
        parts = cleaned.split(",", 1)
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            return None
    return None


async def desktop_click(x: int, y: int) -> Dict[str, Any]:
    """坐标点击：优先 xdotool。"""
    if shutil.which("xdotool"):
        ok, err = _run_cmd(["xdotool", "mousemove", str(x), str(y), "click", "1"])
        if ok:
            return {"success": True, "method": "xdotool", "x": x, "y": y}
        return {"success": False, "error": err}

    try:
        import pyautogui

        pyautogui.click(x, y)
        return {"success": True, "method": "pyautogui", "x": x, "y": y}
    except ImportError:
        return {
            "success": False,
            "error": "桌面点击需要 xdotool 或 pyautogui，请安装 xdotool (apt install xdotool scrot)",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def desktop_type(x: int, y: int, text: str) -> Dict[str, Any]:
    click_res = await desktop_click(x, y)
    if not click_res.get("success"):
        return click_res

    if shutil.which("xdotool"):
        ok, err = _run_cmd(["xdotool", "type", "--delay", "12", "--", text or ""])
        if ok:
            return {"success": True, "method": "xdotool_type", "x": x, "y": y}
        return {"success": False, "error": err}

    try:
        import pyautogui

        pyautogui.write(text or "", interval=0.02)
        return {"success": True, "method": "pyautogui_type", "x": x, "y": y}
    except ImportError:
        return {"success": False, "error": "桌面输入需要 xdotool 或 pyautogui"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute_desktop_action(
    action: str,
    *,
    target_ref: Optional[str] = None,
    value: Optional[str] = None,
    desktop_macro: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """桌面模式原子动作（坐标驱动）。"""
    action = (action or "").lower()
    macro = desktop_macro or {}

    if action == "wait":
        import asyncio

        ms = int(value or 1000)
        await asyncio.sleep(ms / 1000.0)
        return {"success": True, "verification": {"ok": True, "waited_ms": ms}}

    if action in ("click", "type"):
        coord = parse_coord(target_ref or "") or parse_coord(value or "")
        if not coord:
            steps = macro.get("hotspots") or {}
            if target_ref and target_ref in steps:
                hs = steps[target_ref]
                coord = (int(hs.get("x", 0)), int(hs.get("y", 0)))
        if not coord:
            return {"success": False, "error": f"桌面模式需要坐标 target_ref 如 100,200 或 hotspots 配置"}
        x, y = coord
        if action == "click":
            return await desktop_click(x, y)
        return await desktop_type(x, y, str(value or ""))

    if action == "screenshot":
        shot = capture_screenshot_png()
        return {"success": True, "screenshot_len": len(shot)}

    return {"success": False, "error": f"桌面模式不支持动作: {action}"}
