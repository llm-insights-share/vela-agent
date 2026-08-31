"""Structured execution story for AgentChat「思考与执行过程」.

Produces a phase-based narrative (understand → gather → act → verify → deliver)
that the frontend can render without parsing thinking_log strings.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional


PHASE_DEFS = (
    ("understand", "理解任务"),
    ("gather", "收集信息"),
    ("act", "执行操作"),
    ("verify", "核对结果"),
    ("deliver", "生成答复"),
)


def _new_id(prefix: str = "s") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class ExecutionStoryBuilder:
    def __init__(self) -> None:
        self.status = "running"
        self.summary = ""
        self.phases: Dict[str, Dict[str, Any]] = {
            pid: {
                "id": pid,
                "title": title,
                "status": "pending",
                "summary": "",
                "steps": [],
            }
            for pid, title in PHASE_DEFS
        }
        self._started = time.monotonic()
        self._tool_count = 0
        self._iteration = 0

    def ensure_phase(self, phase_id: str, *, active: bool = True) -> Dict[str, Any]:
        phase = self.phases[phase_id]
        if active and phase["status"] in ("pending", "skipped"):
            phase["status"] = "active"
        # mark prior pending phases as skipped when we jump ahead
        order = [p[0] for p in PHASE_DEFS]
        idx = order.index(phase_id)
        for earlier in order[:idx]:
            p = self.phases[earlier]
            if p["status"] == "pending" and not p["steps"]:
                p["status"] = "skipped"
            elif p["status"] == "active" and earlier != phase_id:
                p["status"] = "done"
        return phase

    def complete_phase(self, phase_id: str, summary: str = "") -> None:
        phase = self.phases[phase_id]
        if phase["status"] not in ("error", "hitl"):
            phase["status"] = "done" if phase["steps"] or summary else "skipped"
        if summary:
            phase["summary"] = summary

    def add_step(
        self,
        phase_id: str,
        kind: str,
        title: str,
        *,
        detail: str = "",
        tool_name: str = "",
        tool_call_id: str = "",
        status: str = "ok",
        evidence: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        phase = self.ensure_phase(phase_id, active=True)
        step = {
            "id": _new_id(),
            "kind": kind,
            "title": title,
            "detail": (detail or "")[:4000],
            "tool_name": tool_name or None,
            "tool_call_id": tool_call_id or None,
            "status": status,
            "evidence": evidence,
            "duration_ms": duration_ms,
        }
        phase["steps"].append(step)
        if kind == "tool" or kind in ("code", "ui_skill"):
            self._tool_count += 1
        if status == "fail":
            phase["status"] = "error"
        elif status == "pending" and kind == "hitl":
            phase["status"] = "hitl"
        return step

    def add_intent(self, text: str, *, skill: Optional[str] = None) -> None:
        detail = (text or "").strip()
        title = "任务理解"
        if skill:
            title = f"任务理解 · Skill {skill}"
        self.add_step("understand", "intent", title, detail=detail[:800], status="ok")
        self.complete_phase("understand", detail[:120] if detail else "已理解用户请求")

    def add_rewrite(self, summary: str, original: str = "", rewritten: str = "") -> None:
        detail_parts = [summary] if summary else []
        if original and rewritten and original != rewritten:
            detail_parts.append(f"原文: {original[:200]}")
            detail_parts.append(f"改写: {rewritten[:200]}")
        self.add_step(
            "understand",
            "intent",
            "查询改写",
            detail="\n".join(detail_parts),
            status="ok",
        )

    def add_memory(self, note: str, *, hit: bool) -> None:
        self.add_step(
            "gather",
            "memory",
            "长期记忆召回" if hit else "长期记忆未命中",
            detail=note[:500],
            status="ok" if hit else "skip",
        )

    def add_skill_match(self, name: str, relevance: Optional[float] = None) -> None:
        detail = f"匹配 Skill: {name}"
        if relevance is not None:
            detail += f"（相关度 {relevance:.2f}）"
        self.add_step("understand", "skill", f"启用 Skill · {name}", detail=detail, status="ok")

    def add_knowledge(self, note: str) -> None:
        self.add_step("gather", "knowledge", "知识库上下文", detail=note[:500], status="ok")

    def mark_iteration(self, iteration: int, max_iter: int) -> None:
        self._iteration = iteration
        phase = self.ensure_phase("act", active=True)
        phase["summary"] = f"推理轮次 {iteration}/{max_iter}"

    def add_thought(self, text: str, phase_id: str = "act") -> None:
        preview = (text or "").strip()
        if not preview:
            return
        self.add_step(phase_id, "thought", "思考", detail=preview[:600], status="ok")

    def add_tool_result(
        self,
        tool_name: str,
        result_preview: str,
        *,
        ok: bool = True,
        skipped: bool = False,
        tool_call_id: str = "",
    ) -> None:
        status = "skip" if skipped else ("ok" if ok else "fail")
        kind = "code" if tool_name in ("execute_code", "install_packages") else "tool"
        if tool_name.startswith("cu_") or tool_name.startswith("ui_"):
            if tool_name in ("cu_replay_skill", "ui_replay_skill", "cu_run_task", "cu_search_skills"):
                kind = "ui_skill"
        title = f"调用 {tool_name}"
        if skipped:
            title = f"跳过 {tool_name}"
        elif not ok:
            title = f"{tool_name} 失败"
        evidence = None
        if tool_name in ("tavily_web_search", "duckduckgo_web_search", "web_extract") and result_preview:
            evidence = {"type": "search", "preview": result_preview[:1200]}
        elif tool_name == "tool_search" and result_preview:
            evidence = {"type": "tool_search", "preview": result_preview[:1200]}
        self.add_step(
            "act",
            kind,
            title,
            detail=result_preview[:2000],
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            status=status,
            evidence=evidence,
        )

    def add_check(self, title: str, detail: str = "", *, ok: bool = True) -> None:
        self.add_step(
            "verify",
            "check",
            title,
            detail=detail[:800],
            status="ok" if ok else "fail",
        )
        if ok:
            self.complete_phase("verify", title)
        else:
            self.phases["verify"]["status"] = "error"
            self.phases["verify"]["summary"] = title

    def add_hitl(self, tool_name: str, approval_id: str = "") -> None:
        detail = f"工具 {tool_name} 等待人工审批"
        if approval_id:
            detail += f"（{approval_id}）"
        self.add_step(
            "verify",
            "hitl",
            f"等待审批 · {tool_name}",
            detail=detail,
            tool_name=tool_name,
            status="pending",
        )
        self.status = "hitl_wait"
        self.summary = f"等待审批：{tool_name}"

    def add_error(self, message: str) -> None:
        self.add_step("act", "error", "执行异常", detail=message[:800], status="fail")
        self.status = "error"
        self.summary = message[:120]

    def add_deliver(self, note: str = "已生成正式答复") -> None:
        self.add_step("deliver", "thought", note, status="ok")
        self.complete_phase("deliver", note)

    def finalize(
        self,
        *,
        status: str = "done",
        summary: str = "",
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self.status not in ("hitl_wait", "error", "aborted"):
            self.status = status
        # close open phases
        for pid, _ in PHASE_DEFS:
            phase = self.phases[pid]
            if phase["status"] == "active":
                phase["status"] = "done" if phase["steps"] else "skipped"
            if phase["status"] == "pending" and not phase["steps"]:
                phase["status"] = "skipped"
            if not phase["summary"] and phase["steps"]:
                last = phase["steps"][-1]
                phase["summary"] = last.get("title") or ""

        if not self.summary:
            self.summary = summary or self._auto_summary()

        elapsed_ms = int((time.monotonic() - self._started) * 1000)
        m = dict(metrics or {})
        m.setdefault("elapsed_ms", elapsed_ms)
        m.setdefault("tool_calls", self._tool_count)
        m.setdefault("iterations", self._iteration)

        return {
            "version": 1,
            "status": self.status,
            "summary": self.summary,
            "phases": [self.phases[pid] for pid, _ in PHASE_DEFS if self.phases[pid]["status"] != "skipped" or self.phases[pid]["steps"]],
            "metrics": m,
        }

    def _auto_summary(self) -> str:
        parts: List[str] = []
        for pid, title in PHASE_DEFS:
            phase = self.phases[pid]
            if phase["status"] in ("done", "error", "hitl") and phase["steps"]:
                parts.append(phase["summary"] or title)
        if self.status == "hitl_wait":
            return " · ".join(parts[-3:]) or "等待人工审批"
        if self.status == "error":
            return " · ".join(parts[-3:]) or "执行出错"
        return " → ".join(parts[:4]) if parts else "已完成"

    @classmethod
    def from_thinking_log(
        cls,
        thinking: str,
        *,
        user_message: str = "",
        active_skill: Optional[str] = None,
        status: str = "done",
    ) -> Dict[str, Any]:
        """Synthesize a story from legacy thinking_log text (history fallback)."""
        builder = cls()
        if user_message:
            builder.add_intent(user_message[:200], skill=active_skill)
        elif active_skill:
            builder.add_skill_match(active_skill)

        if not thinking:
            return builder.finalize(status=status)

        for raw in thinking.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("[QueryRewrite]") or line.startswith("原文:") or line.startswith("改写:"):
                builder.add_step("understand", "intent", "查询改写", detail=line, status="ok")
            elif line.startswith("[Memory]"):
                hit = "未召回" not in line and "失败" not in line
                builder.add_memory(line, hit=hit)
            elif re.match(r"^\[ReAct|^\[Direct\]|^\[Plan-and-Execute\]", line):
                builder.add_step("act", "thought", line[:80], status="ok")
            elif line.startswith("思考:") or line.startswith("[规划]") or line.startswith("计划内容:"):
                builder.add_thought(line)
            elif m := re.match(r"^工具\s*\[([^\]]+)\]\s*(?:结果:|:)\s*(.*)$", line):
                name, preview = m.group(1), m.group(2)
                ok = "错误" not in preview and "失败" not in preview[:20]
                skipped = "已跳过" in preview or "预算" in preview[:20]
                builder.add_tool_result(name, preview, ok=ok, skipped=skipped)
            elif line.startswith("[TIMEOUT]") or line.startswith("[中止]"):
                builder.add_error(line)
            elif "质检" in line or "校验" in line:
                builder.add_check(line[:80], line, ok="失败" not in line)
            elif line.startswith("[文件]") or line.startswith("[代码执行]") or line.startswith("[UI技能]"):
                builder.add_step("act", "thought", line[:100], detail=line, status="ok")
            elif line.startswith("调用 ") and "工具" in line:
                builder.add_step("act", "thought", line, status="ok")

        if status == "done" and builder.status == "running":
            builder.add_deliver()
        return builder.finalize(status=status if builder.status == "running" else builder.status)
