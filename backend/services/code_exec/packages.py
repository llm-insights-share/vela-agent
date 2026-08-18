"""Controlled package installation into sandbox venv."""

import asyncio
import os
import re
import subprocess
import sys
import threading
from typing import Any, Dict, List

from services.code_exec.config import (
    DATA_DIR,
    DEFAULT_VENV_PATH,
    load_code_exec_config,
)

_install_lock = threading.Lock()

PACKAGE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-]*$")

SANDBOX_REQUIREMENTS = os.path.join(
    os.path.dirname(__file__), "requirements-sandbox.txt"
)


def _validate_package_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("包名不能为空")
    if any(x in name for x in (";", "@", "://", " ", "[", "]", "git+", "-e")):
        raise ValueError(f"不允许的包名格式: {name}")
    base = name.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0]
    if not PACKAGE_NAME_RE.match(base):
        raise ValueError(f"非法包名: {name}")
    return name


def ensure_sandbox_venv() -> str:
    """Create sandbox venv and install base packages if missing."""
    cfg = load_code_exec_config()
    venv_path = cfg.resolved_venv_path

    python_bin = cfg.python_executable
    if os.path.isfile(python_bin):
        return venv_path

    os.makedirs(os.path.dirname(venv_path) or DATA_DIR, exist_ok=True)

    subprocess.run(
        [sys.executable, "-m", "venv", venv_path],
        check=True,
        capture_output=True,
        text=True,
    )

    pip = cfg.pip_executable
    reqs = SANDBOX_REQUIREMENTS
    if os.path.isfile(reqs):
        subprocess.run(
            [pip, "install", "--no-input", "--disable-pip-version-check", "-r", reqs],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    else:
        subprocess.run(
            [pip, "install", "--no-input", "--disable-pip-version-check",
             "pandas", "numpy", "matplotlib", "openpyxl", "tabulate", "dill"],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )

    return venv_path


async def install_packages(names: List[str]) -> Dict[str, Any]:
    cfg = load_code_exec_config()
    if not cfg.enabled:
        return {"success": False, "error": "代码执行功能已禁用"}
    if not cfg.allow_install:
        return {"success": False, "error": "包安装功能已禁用"}

    if not names:
        return {"success": False, "error": "缺少 packages 参数"}

    validated: List[str] = []
    allowlist = {p.lower() for p in cfg.package_allowlist}
    for raw in names:
        pkg = _validate_package_name(raw)
        base = pkg.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].lower()
        if base not in allowlist:
            return {
                "success": False,
                "error": f"包 '{base}' 不在白名单中。允许: {', '.join(cfg.package_allowlist)}",
            }
        validated.append(pkg)

    ensure_sandbox_venv()
    pip = cfg.pip_executable

    def _run_install() -> subprocess.CompletedProcess:
        with _install_lock:
            return subprocess.run(
                [pip, "install", "--no-input", "--disable-pip-version-check"] + validated,
                capture_output=True,
                text=True,
                timeout=300,
            )

    try:
        loop = asyncio.get_running_loop()
        proc = await loop.run_in_executor(None, _run_install)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "pip install 超时 (300s)"}
    except Exception as e:
        return {"success": False, "error": f"安装失败: {e}"}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[:2000]
        return {"success": False, "error": f"pip install 失败:\n{err}"}

    return {
        "success": True,
        "result": f"已安装: {', '.join(validated)}",
        "packages": validated,
    }
