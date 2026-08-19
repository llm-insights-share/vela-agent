"""Hardened host sandbox runner for Python and JavaScript."""

from __future__ import annotations

import asyncio
import os
import platform
import resource
import signal
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

from services.code_exec.bootstrap import build_python_script, parse_meta_from_stdout
from services.code_exec.config import load_code_exec_config
from services.code_exec.packages import ensure_sandbox_venv
from services.code_exec.workspace import SessionWorkspace

ALLOWED_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "MPLBACKEND", "TZ")


def _build_sandbox_env(workspace: SessionWorkspace, cfg) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key in ALLOWED_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val

    env["HOME"] = str(workspace.root)
    env["TMPDIR"] = str(workspace.root / ".tmp")
    os.makedirs(env["TMPDIR"], exist_ok=True)
    env["MPLBACKEND"] = "Agg"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    venv_bin = os.path.dirname(cfg.python_executable)
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "/usr/bin:/bin")

    if not cfg.allow_network:
        for proxy_key in (
            "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
            "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy",
        ):
            env.pop(proxy_key, None)

    return env


def _make_preexec_fn(cfg):
    def _preexec():
        try:
            os.setsid()
        except OSError:
            pass

        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cfg.cpu_seconds, cfg.cpu_seconds + 5))
        except (ValueError, OSError):
            pass

        try:
            max_fsize = 50 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (max_fsize, max_fsize))
        except (ValueError, OSError):
            pass

        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        except (ValueError, OSError):
            pass

        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
        except (ValueError, OSError):
            pass

        if platform.system() == "Linux" and cfg.memory_mb > 0:
            try:
                mem_bytes = cfg.memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, OSError):
                pass

    return _preexec


def _write_network_block_sitecustomize(workspace: SessionWorkspace) -> Optional[str]:
    """Write sitecustomize.py that blocks outbound socket connects."""
    site_dir = workspace.root / ".tmp" / "site-packages"
    site_dir.mkdir(parents=True, exist_ok=True)
    sitecustomize = site_dir / "sitecustomize.py"
    sitecustomize.write_text(
        'import socket\n'
        '_orig_connect = socket.socket.connect\n'
        'def _blocked_connect(self, address):\n'
        '    if self.family == socket.AF_UNIX:\n'
        '        return _orig_connect(self, address)\n'
        '    raise PermissionError("Network access disabled in sandbox")\n'
        'socket.socket.connect = _blocked_connect\n',
        encoding="utf-8",
    )
    return str(site_dir)


async def _read_stream_with_limit(stream, max_bytes: int) -> tuple[bytes, bool]:
    chunks: List[bytes] = []
    total = 0
    truncated = False
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        remaining = max_bytes - total
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), truncated


async def _run_subprocess(
    cmd: List[str],
    *,
    cwd: str,
    env: Dict[str, str],
    timeout: int,
    max_output_bytes: int,
    preexec_fn=None,  # kept for callers; ignored (fork+OpenMP deadlock)
) -> Dict[str, Any]:
    start = time.monotonic()
    _ = preexec_fn
    # Do not pass preexec_fn: it forces fork() and can deadlock the uvloop
    # in OpenMP/PyTorch atfork after sentence-transformers is loaded.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )

    stdout_task = asyncio.create_task(_read_stream_with_limit(proc.stdout, max_output_bytes))
    stderr_task = asyncio.create_task(_read_stream_with_limit(proc.stderr, max_output_bytes))

    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()

    stdout_bytes, stdout_trunc = await stdout_task
    stderr_bytes, stderr_trunc = await stderr_task

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout_str = stdout_bytes.decode("utf-8", errors="replace")
    stderr_str = stderr_bytes.decode("utf-8", errors="replace")

    return {
        "exit_code": proc.returncode if not timed_out else -9,
        "stdout": stdout_str,
        "stderr": stderr_str,
        "stdout_truncated": stdout_trunc,
        "stderr_truncated": stderr_trunc,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
    }


class HostSandboxRunner:
    """Execute code in an isolated sandbox venv with resource limits."""

    async def run(
        self,
        code: str,
        *,
        language: str = "python",
        timeout: Optional[int] = None,
        workspace: SessionWorkspace,
        output_dir: str = "",
        reset_state: bool = False,
    ) -> Dict[str, Any]:
        cfg = load_code_exec_config()
        if not cfg.enabled:
            return {"success": False, "error": "代码执行功能已禁用"}

        workspace.ensure()
        if reset_state:
            workspace.reset_state()

        wall_timeout = timeout or cfg.wall_timeout
        before_snap = workspace.snapshot()

        if language == "python":
            result = await self._run_python(code, workspace, cfg, wall_timeout, output_dir)
        elif language == "javascript":
            result = await self._run_javascript(code, workspace, cfg, wall_timeout, output_dir)
        else:
            return {"success": False, "error": f"不支持的语言: {language}"}

        after_snap = workspace.snapshot()
        artifacts = workspace.sweep_artifacts(before_snap, after_snap)

        if output_dir:
            for art in artifacts:
                if art.get("kind") != "skipped" and art.get("path"):
                    copied = workspace.copy_artifact_to_output(art["path"], output_dir)
                    if copied:
                        art["output_path"] = copied

        result["artifacts"] = artifacts
        return result

    async def _run_python(
        self,
        code: str,
        workspace: SessionWorkspace,
        cfg,
        timeout: int,
        output_dir: str,
    ) -> Dict[str, Any]:
        ensure_sandbox_venv()
        state_file = str(workspace.state_dir / "globals.pkl")
        script_body = build_python_script(
            code,
            workspace_root=str(workspace.root),
            state_file=state_file,
            state_persist=cfg.state_persist,
        )
        script_path = workspace.next_script_path("python")
        script_path.write_text(script_body, encoding="utf-8")

        env = _build_sandbox_env(workspace, cfg)
        if not cfg.allow_network:
            site_dir = _write_network_block_sitecustomize(workspace)
            if site_dir:
                existing = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = site_dir + (os.pathsep + existing if existing else "")

        preexec = _make_preexec_fn(cfg)
        run_result = await _run_subprocess(
            [cfg.python_executable, str(script_path)],
            cwd=str(workspace.root),
            env=env,
            timeout=timeout,
            max_output_bytes=cfg.max_output_bytes,
            preexec_fn=preexec,
        )

        return self._format_result(run_result, code, "python")

    async def _run_javascript(
        self,
        code: str,
        workspace: SessionWorkspace,
        cfg,
        timeout: int,
        output_dir: str,
    ) -> Dict[str, Any]:
        node_check = await _run_subprocess(
            ["node", "--version"],
            cwd=str(workspace.root),
            env=_build_sandbox_env(workspace, cfg),
            timeout=5,
            max_output_bytes=1024,
        )
        if node_check.get("exit_code", 1) != 0:
            return {"success": False, "error": "Node.js 未安装或不可用"}

        script_path = workspace.next_script_path("javascript")
        script_path.write_text(code, encoding="utf-8")

        env = _build_sandbox_env(workspace, cfg)
        preexec = _make_preexec_fn(cfg)

        run_result = await _run_subprocess(
            ["node", str(script_path)],
            cwd=str(workspace.root),
            env=env,
            timeout=timeout,
            max_output_bytes=cfg.max_output_bytes,
            preexec_fn=preexec,
        )

        return self._format_result(run_result, code, "javascript")

    def _format_result(self, run_result: Dict[str, Any], code: str, language: str) -> Dict[str, Any]:
        stdout = run_result.get("stdout", "")
        stderr = run_result.get("stderr", "")
        meta = None

        if language == "python":
            stdout, meta = parse_meta_from_stdout(stdout)

        exit_code = run_result.get("exit_code", 1)
        timed_out = run_result.get("timed_out", False)
        duration_ms = run_result.get("duration_ms", 0)

        if timed_out:
            return {
                "success": False,
                "error": f"代码执行超时",
                "stdout": stdout[:5000],
                "stderr": stderr[:2000],
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "code": code,
                "language": language,
            }

        if exit_code != 0:
            error_msg = stderr.strip() or stdout.strip() or f"exit code {exit_code}"
            return {
                "success": False,
                "error": f"代码执行出错 (exit code {exit_code}):\n{error_msg[:3000]}",
                "stdout": stdout[:5000],
                "stderr": stderr[:2000],
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "code": code,
                "language": language,
                "meta": meta,
            }

        result_parts = []
        if stdout:
            result_parts.append(stdout)
        if stderr:
            result_parts.append(f"[stderr]\n{stderr}")

        out: Dict[str, Any] = {
            "success": True,
            "result": "\n".join(result_parts) if result_parts else "(无输出)",
            "stdout": stdout[:5000],
            "stderr": stderr[:2000],
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "code": code,
            "language": language,
            "meta": meta,
        }

        if run_result.get("stdout_truncated") or run_result.get("stderr_truncated"):
            out["output_truncated"] = True

        if meta:
            skipped = meta.get("state_skipped", 0)
            if skipped:
                out["state_skipped"] = skipped

        return out


_runner = HostSandboxRunner()


async def run_code(
    code: str,
    output_dir: str,
    *,
    language: str = "python",
    timeout: Optional[int] = None,
    reset_state: bool = False,
) -> Dict[str, Any]:
    """High-level entry used by builtin_tools."""
    workspace = SessionWorkspace.from_output_dir(output_dir)
    return await _runner.run(
        code,
        language=language,
        timeout=timeout,
        workspace=workspace,
        output_dir=output_dir,
        reset_state=reset_state,
    )
