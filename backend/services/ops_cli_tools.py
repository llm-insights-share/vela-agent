"""LOCAL_PYTHON tools that wrap `python -m vela_cli` for the ops assistant."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional

from services.tool_runtime_context import get_api_token

# Ensure backend root is importable when invoked as LOCAL_PYTHON
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_api_base() -> str:
    return (os.environ.get("VELA_API_BASE") or "http://127.0.0.1:8000/api/v1").rstrip("/")


def _run_cli(argv: List[str], timeout: int = 120) -> Dict[str, Any]:
    """Run `python -m vela_cli --json ...` and return parsed JSON."""
    cmd = [sys.executable, "-m", "vela_cli", "--json", *argv]
    env = os.environ.copy()
    env["PYTHONPATH"] = _BACKEND_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["VELA_API_BASE"] = env.get("VELA_API_BASE") or _default_api_base()
    token = get_api_token() or env.get("VELA_API_TOKEN", "")
    if token:
        env["VELA_API_TOKEN"] = token
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_BACKEND_ROOT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"vela CLI timed out after {timeout}s", "command": cmd}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    parsed: Any = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = {"raw": stdout}
    if proc.returncode != 0:
        err_body = parsed if isinstance(parsed, dict) else {"raw": stdout or stderr}
        return {
            "success": False,
            "exit_code": proc.returncode,
            "error": err_body.get("body") or err_body.get("message") or stderr or stdout or "CLI failed",
            "result": err_body,
            "command": " ".join(shlex.quote(c) for c in cmd),
        }
    return {
        "success": True,
        "result": parsed if parsed is not None else {"ok": True},
        "command": " ".join(shlex.quote(c) for c in cmd),
    }


def vela_run(subcommand: str, args_json: str = "[]") -> Dict[str, Any]:
    """Generic CLI runner.

    Args:
        subcommand: Space-separated command path, e.g. "agents list" or "tools get".
        args_json: JSON array of extra CLI args, e.g. '["--page","1"]' or '["TOOL_ID"]'.
    """
    parts = [p for p in (subcommand or "").split() if p]
    if not parts:
        return {"success": False, "error": "subcommand is required"}
    try:
        extra = json.loads(args_json) if args_json else []
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"args_json must be a JSON array: {exc}"}
    if not isinstance(extra, list):
        return {"success": False, "error": "args_json must be a JSON array of strings"}
    argv = parts + [str(x) for x in extra]
    return _run_cli(argv)


def vela_agents_list(page: int = 1, page_size: int = 50, keyword: str = "", status: str = "") -> Dict[str, Any]:
    args: List[str] = ["agents", "list", "--page", str(page), "--page-size", str(page_size)]
    if keyword:
        args.extend(["--name", keyword])
    if status:
        args.extend(["--status", status])
    return _run_cli(args)


def vela_agents_get(agent_id: str) -> Dict[str, Any]:
    return _run_cli(["agents", "get", agent_id])


def vela_agents_create(
    name: str,
    model_service_id: str,
    description: str = "",
    system_prompt: str = "",
    agent_type: str = "SINGLE",
    json_body: str = "",
) -> Dict[str, Any]:
    if json_body:
        return _run_cli(["agents", "create", "--json-body", json_body])
    args = [
        "agents", "create",
        "--name", name,
        "--model-service-id", model_service_id,
        "--description", description or "",
        "--system-prompt", system_prompt or "",
        "--agent-type", agent_type or "SINGLE",
    ]
    return _run_cli(args)


def vela_agents_update(agent_id: str, json_body: str) -> Dict[str, Any]:
    return _run_cli(["agents", "update", agent_id, "--json-body", json_body])


def vela_agents_delete(agent_id: str) -> Dict[str, Any]:
    return _run_cli(["agents", "delete", agent_id])


def vela_agents_publish(agent_id: str, change_summary: str = "") -> Dict[str, Any]:
    args = ["agents", "publish", agent_id]
    if change_summary:
        args.extend(["--change-summary", change_summary])
    return _run_cli(args)


def vela_agents_bind_tools(agent_id: str, json_body: str) -> Dict[str, Any]:
    return _run_cli(["agents", "bind-tools", agent_id, "--json-body", json_body])


def vela_tools_list(page: int = 1, page_size: int = 50, keyword: str = "") -> Dict[str, Any]:
    args = ["tools", "list", "--page", str(page), "--page-size", str(page_size)]
    if keyword:
        args.extend(["--keyword", keyword])
    return _run_cli(args)


def vela_tools_get(tool_id: str) -> Dict[str, Any]:
    return _run_cli(["tools", "get", tool_id])


def vela_tools_create(json_body: str) -> Dict[str, Any]:
    return _run_cli(["tools", "create", "--json-body", json_body])


def vela_tools_update(tool_id: str, json_body: str) -> Dict[str, Any]:
    return _run_cli(["tools", "update", tool_id, "--json-body", json_body])


def vela_tools_delete(tool_id: str) -> Dict[str, Any]:
    return _run_cli(["tools", "delete", tool_id])


def vela_skills_list(page: int = 1, page_size: int = 50, keyword: str = "") -> Dict[str, Any]:
    args = ["skills", "list", "--page", str(page), "--page-size", str(page_size)]
    if keyword:
        args.extend(["--keyword", keyword])
    return _run_cli(args)


def vela_skills_get(skill_pack_id: str) -> Dict[str, Any]:
    return _run_cli(["skills", "get", skill_pack_id])


def vela_kb_list(page: int = 1, page_size: int = 50, keyword: str = "") -> Dict[str, Any]:
    args = ["kb", "list", "--page", str(page), "--page-size", str(page_size)]
    if keyword:
        args.extend(["--keyword", keyword])
    return _run_cli(args)


def vela_kb_get(kb_id: str) -> Dict[str, Any]:
    return _run_cli(["kb", "get", kb_id])


def vela_approvals_list(
    page: int = 1,
    page_size: int = 50,
    status: str = "PENDING",
    category: str = "",
) -> Dict[str, Any]:
    args = ["approvals", "list", "--page", str(page), "--page-size", str(page_size)]
    if status:
        args.extend(["--status", status])
    if category:
        args.extend(["--category", category])
    return _run_cli(args)


def vela_approvals_get(approval_id: str) -> Dict[str, Any]:
    return _run_cli(["approvals", "get", approval_id])


def vela_approvals_approve(
    approval_id: str,
    session_id: str,
    reviewer: str = "vela-ops-assistant",
    comment: str = "",
) -> Dict[str, Any]:
    args = [
        "approvals", "approve", approval_id,
        "--session-id", session_id,
        "--reviewer", reviewer or "vela-ops-assistant",
    ]
    if comment:
        args.extend(["--comment", comment])
    return _run_cli(args)


def vela_approvals_reject(
    approval_id: str,
    session_id: str,
    reviewer: str = "vela-ops-assistant",
    comment: str = "",
) -> Dict[str, Any]:
    args = [
        "approvals", "reject", approval_id,
        "--session-id", session_id,
        "--reviewer", reviewer or "vela-ops-assistant",
    ]
    if comment:
        args.extend(["--comment", comment])
    return _run_cli(args)


def vela_sessions_list(page: int = 1, page_size: int = 20, agent_id: str = "", status: str = "") -> Dict[str, Any]:
    args = ["sessions", "list", "--page", str(page), "--page-size", str(page_size)]
    if agent_id:
        args.extend(["--agent-id", agent_id])
    if status:
        args.extend(["--status", status])
    return _run_cli(args)


def vela_models_list(page: int = 1, page_size: int = 50) -> Dict[str, Any]:
    return _run_cli(["models", "list", "--page", str(page), "--page-size", str(page_size)])


def vela_schedules_list(page: int = 1, page_size: int = 50) -> Dict[str, Any]:
    return _run_cli(["schedules", "list", "--page", str(page), "--page-size", str(page_size)])


def vela_connectors_list() -> Dict[str, Any]:
    return _run_cli(["connectors", "list"])


def vela_memory_scopes_list() -> Dict[str, Any]:
    """List Letta memory scopes (agent/user mappings)."""
    return _run_cli(["memory", "scopes"])


def vela_memory_passages_list(
    agent_id: str,
    user_id: str = "",
    page: int = 1,
    page_size: int = 50,
    query: str = "",
) -> Dict[str, Any]:
    """List archived memory passages for an agent scope."""
    if not (agent_id or "").strip():
        return {
            "success": False,
            "error": "缺少必填参数 agent_id。请先向用户确认要写入/查看哪个智能体的记忆（可用 vela_agents_list 帮助选择）。",
            "need_params": ["agent_id"],
        }
    args = [
        "memory", "passages",
        "--agent-id", agent_id,
        "--page", str(page),
        "--page-size", str(page_size),
    ]
    if user_id:
        args.extend(["--user-id", user_id])
    if query:
        args.extend(["--query", query])
    res = _run_cli(args)
    # Filter empty passage content from tool result
    if isinstance(res, dict) and res.get("success"):
        inner = res.get("result")
        if isinstance(inner, dict) and isinstance(inner.get("items"), list):
            before = len(inner["items"])
            inner["items"] = [
                it for it in inner["items"]
                if isinstance(it, dict) and str(it.get("content") or it.get("text") or "").strip()
            ]
            if isinstance(inner.get("total"), int):
                inner["total"] = max(0, inner["total"] - (before - len(inner["items"])))
            else:
                inner["total"] = len(inner["items"])
    return res


def vela_memory_passages_create(
    agent_id: str,
    text: str,
    user_id: str = "",
    tags: str = "",
) -> Dict[str, Any]:
    """Create an archived memory passage in Memory Management (Letta).

    tags: comma-separated string.
    """
    if not (user_id or "").strip():
        try:
            from services.tool_runtime_context import get_caller_id
            user_id = get_caller_id() or ""
        except Exception:
            user_id = ""
    missing = []
    if not (agent_id or "").strip():
        missing.append("agent_id")
    if not (text or "").strip():
        missing.append("text")
    if missing:
        return {
            "success": False,
            "error": (
                f"缺少必填参数: {', '.join(missing)}。"
                "请向用户确认：要写入哪个智能体（agent_id），以及记忆正文（text）；"
                "user_id/tags 可选。"
            ),
            "need_params": missing,
        }
    args = [
        "memory", "create-passage",
        "--agent-id", agent_id,
        "--text", text,
    ]
    if user_id:
        args.extend(["--user-id", user_id])
    for t in [x.strip() for x in (tags or "").split(",") if x.strip()]:
        args.extend(["--tag", t])
    res = _run_cli(args)
    # Ensure navigation can resolve /memory?agent_id=
    if isinstance(res, dict) and res.get("success"):
        inner = res.get("result")
        if isinstance(inner, dict):
            inner.setdefault("agent_id", agent_id)
            if user_id:
                inner.setdefault("user_id", user_id)
        else:
            res["agent_id"] = agent_id
            if user_id:
                res["user_id"] = user_id
    return res
