"""
WF: 工作流运行时执行引擎
WF-IMP-06~11
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import (
    Agent, AgentToolBinding, AuditLog, HITLApproval, ModelProvider, ModelService,
    Session as SessionModel, SessionStatus, Tool, gen_uuid, now_utc,
)
from services.workflow_compiler import WorkflowCompiler, CompiledWorkflow

logger = logging.getLogger(__name__)


@dataclass
class NodeExecutionRecord:
    node_id: str
    node_type: str
    label: str = ""
    status: str = "success"  # success | failed | skipped | hitl_wait
    input_summary: str = ""
    output: str = ""
    duration_ms: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowState:
    input: str = ""
    variables: Dict[str, Any] = field(default_factory=dict)
    current_node_id: Optional[str] = None
    next_node_id: Optional[str] = None
    trace: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "running"  # running | hitl_wait | completed | failed | aborted
    final_result: str = ""
    total_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": self.input,
            "variables": self.variables,
            "current_node_id": self.current_node_id,
            "next_node_id": self.next_node_id,
            "trace": self.trace,
            "status": self.status,
            "final_result": self.final_result,
            "total_tokens": self.total_tokens,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "WorkflowState":
        return WorkflowState(
            input=data.get("input", ""),
            variables=data.get("variables") or {},
            current_node_id=data.get("current_node_id"),
            next_node_id=data.get("next_node_id"),
            trace=data.get("trace") or [],
            status=data.get("status", "running"),
            final_result=data.get("final_result", ""),
            total_tokens=data.get("total_tokens", 0),
        )


class WorkflowEngine:
    """工作流状态机执行器"""

    def __init__(
        self,
        db: Session,
        agent: Agent,
        session: SessionModel,
        provider: ModelProvider,
        model_svc: ModelService,
    ):
        self.db = db
        self.agent = agent
        self.session = session
        self.provider = provider
        self.model_svc = model_svc
        self.compiled = WorkflowCompiler.compile(agent.workflow_definition or {})
        self.trace_id = session.trace_id or str(uuid.uuid4())
        self.thinking_log: List[str] = []

    async def run(
        self,
        user_message: str,
        entry_node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """从 start 或 cron 入口执行工作流"""
        if not self.compiled.nodes:
            return {"success": False, "error": "工作流未配置"}

        start_id = entry_node_id or self.compiled.start_node_id
        if not start_id or start_id not in self.compiled.nodes:
            return {"success": False, "error": "工作流缺少有效入口节点"}

        state = WorkflowState(
            input=user_message,
            variables={"__input__": user_message},
            current_node_id=start_id,
            status="running",
        )

        # start/cron 节点仅作入口，立即跳到下一节点
        entry_type = self.compiled.nodes[start_id].get("type")
        if entry_type in ("start", "cron"):
            next_ids = self._get_next_node_ids(start_id)
            if not next_ids:
                return {"success": False, "error": f"入口节点 {start_id} 无后续连接"}
            state.current_node_id = next_ids[0]

        return await self._execute_from(state)

    async def resume(self, state: WorkflowState, hitl_approved: bool = True) -> Dict[str, Any]:
        """WF-IMP-08: HITL 审批后恢复执行"""
        if not hitl_approved:
            state.status = "aborted"
            state.final_result = "工作流在 HITL 审批节点被拒绝"
            return self._build_response(state)

        next_id = state.next_node_id
        if not next_id:
            return {"success": False, "error": "无法恢复：缺少下一节点 ID"}

        state.status = "running"
        state.current_node_id = next_id
        state.next_node_id = None
        return await self._execute_from(state)

    async def _execute_from(self, state: WorkflowState) -> Dict[str, Any]:
        max_steps = 100
        steps = 0

        while state.current_node_id and steps < max_steps:
            steps += 1
            node_id = state.current_node_id
            node = self.compiled.nodes.get(node_id)
            if not node:
                state.status = "failed"
                state.final_result = f"节点不存在: {node_id}"
                break

            ntype = node.get("type")
            data = node.get("data") or {}
            label = data.get("label") or node_id

            if ntype in ("start", "cron"):
                next_ids = self._get_next_node_ids(node_id)
                state.current_node_id = next_ids[0] if next_ids else None
                continue

            if ntype == "end":
                state.status = "completed"
                state.final_result = self._resolve_output(data.get("output_template"), state) or self._last_output(state)
                record = NodeExecutionRecord(
                    node_id=node_id, node_type=ntype, label=label,
                    status="success", output=state.final_result,
                )
                state.trace.append(record.to_dict())
                self._audit(node_id, ntype, record)
                state.current_node_id = None
                break

            result = await self._execute_node_with_retry(node_id, node, state)

            if result.get("hitl_pending"):
                state.status = "hitl_wait"
                state.next_node_id = result.get("next_node_id")
                return self._build_response(state, pending_approval_id=result.get("approval_id"))

            if result.get("status") == "failed" and result.get("abort"):
                state.status = "failed"
                state.final_result = result.get("error", "节点执行失败")
                break

            if result.get("status") == "skipped":
                next_ids = self._get_next_node_ids(node_id)
                state.current_node_id = next_ids[0] if next_ids else None
                continue

            output = result.get("output", "")
            state.variables[node_id] = output

            record = NodeExecutionRecord(
                node_id=node_id,
                node_type=ntype,
                label=label,
                status=result.get("status", "success"),
                input_summary=result.get("input_summary", "")[:500],
                output=str(output)[:2000],
                duration_ms=result.get("duration_ms", 0),
                error=result.get("error", ""),
            )
            state.trace.append(record.to_dict())
            self._audit(node_id, ntype, record)

            if ntype == "condition":
                branch = result.get("branch", "false")
                state.current_node_id = self._get_condition_target(node_id, branch)
            else:
                next_ids = self._get_next_node_ids(node_id)
                state.current_node_id = next_ids[0] if next_ids else None

        if steps >= max_steps:
            state.status = "failed"
            state.final_result = "工作流执行超过最大步数限制"

        if state.status == "running" and not state.current_node_id:
            state.status = "completed"
            if not state.final_result:
                state.final_result = self._last_output(state)

        return self._build_response(state)

    async def _execute_node_with_retry(
        self, node_id: str, node: Dict[str, Any], state: WorkflowState
    ) -> Dict[str, Any]:
        data = node.get("data") or {}
        retry_count = data.get("retry_count", 0) or 0
        retry_interval = data.get("retry_interval_seconds", 5) or 5
        on_failure = data.get("on_failure", "abort")

        last_error = ""
        attempts = 1 + retry_count

        for attempt in range(attempts):
            try:
                result = await self._execute_node(node_id, node, state)
                if result.get("status") != "failed":
                    return result
                last_error = result.get("error", "未知错误")
            except Exception as e:
                last_error = str(e)
                logger.error(f"节点 {node_id} 执行异常: {e}", exc_info=True)

            if attempt < attempts - 1:
                self.thinking_log.append(
                    f"[WF] 节点 {node_id} 失败，{retry_interval}s 后重试 ({attempt + 1}/{attempts})"
                )
                await asyncio.sleep(retry_interval)

        if on_failure == "skip":
            record = NodeExecutionRecord(
                node_id=node_id, node_type=node.get("type", ""),
                label=data.get("label", node_id), status="skipped", error=last_error,
            )
            state.trace.append(record.to_dict())
            return {"status": "skipped", "error": last_error}

        if on_failure == "retry":
            return {"status": "failed", "error": last_error, "abort": True}

        return {"status": "failed", "error": last_error, "abort": True}

    async def _execute_node(
        self, node_id: str, node: Dict[str, Any], state: WorkflowState
    ) -> Dict[str, Any]:
        ntype = node.get("type")
        data = node.get("data") or {}
        timeout = data.get("timeout_seconds", 60) or 60
        start = time.time()

        self.thinking_log.append(f"[WF] 执行节点 {node_id} ({ntype})")

        if ntype == "llm":
            output, tokens = await asyncio.wait_for(
                self._run_llm_node(data, state),
                timeout=float(timeout),
            )
            state.total_tokens += tokens
            return {
                "status": "success",
                "output": output,
                "duration_ms": int((time.time() - start) * 1000),
            }

        if ntype == "tool":
            output = await asyncio.wait_for(
                self._run_tool_node(data, state),
                timeout=float(timeout),
            )
            return {
                "status": "success",
                "output": output,
                "duration_ms": int((time.time() - start) * 1000),
            }

        if ntype == "condition":
            branch = self._eval_condition(data.get("expression", ""), state)
            return {
                "status": "success",
                "output": branch,
                "branch": branch,
                "duration_ms": int((time.time() - start) * 1000),
            }

        if ntype == "hitl":
            return await self._run_hitl_node(node_id, data, state)

        if ntype == "subgraph":
            output, tokens = await asyncio.wait_for(
                self._run_subgraph_node(data, state),
                timeout=float(timeout),
            )
            state.total_tokens += tokens
            return {
                "status": "success",
                "output": output,
                "duration_ms": int((time.time() - start) * 1000),
            }

        if ntype == "screenpilot":
            return await self._run_screenpilot_node(node_id, data, state)

        return {"status": "failed", "error": f"不支持的节点类型: {ntype}"}

    async def _run_llm_node(self, data: Dict[str, Any], state: WorkflowState) -> tuple:
        from services.model_provider import model_provider_service

        prompt = self._resolve_template(data.get("prompt", ""), state)
        ms_id = data.get("model_service_id") or self.agent.model_service_id

        model_svc = self.db.query(ModelService).filter(
            ModelService.model_service_id == ms_id
        ).first()
        if not model_svc:
            raise ValueError(f"模型服务不存在: {ms_id}")

        provider = self.db.query(ModelProvider).filter(
            ModelProvider.provider_id == model_svc.provider_id
        ).first()
        if not provider:
            raise ValueError("模型供应商不存在")

        messages = [{"role": "user", "content": prompt}]
        max_tokens = data.get("max_tokens") or self.agent.single_call_token_limit or 4096

        completion = await model_provider_service.chat_completion(
            provider=provider,
            model_name=model_svc.model_name,
            messages=messages,
            max_tokens=max_tokens,
            timeout_seconds=data.get("timeout_seconds", 60),
        )

        content = completion.get("choices", [{}])[0].get("message", {}).get("content", "")
        tokens = completion.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    async def _run_tool_node(self, data: Dict[str, Any], state: WorkflowState) -> str:
        from services.builtin_tools import BUILTIN_TOOLS, execute_builtin_tool
        from services.tool_service import tool_execution_service

        tool_id = data.get("tool_id")
        tool_name = data.get("tool_name")
        params_raw = data.get("parameters") or data.get("tool_args") or "{}"
        if isinstance(params_raw, str):
            params = json.loads(self._resolve_template(params_raw, state) or "{}")
        else:
            params = {k: self._resolve_template(str(v), state) for k, v in params_raw.items()}

        for bt in BUILTIN_TOOLS:
            if bt.name == tool_name or bt.name == data.get("builtin_tool"):
                output_dir = f"/tmp/vela_wf_{self.session.session_id}"
                import os
                os.makedirs(output_dir, exist_ok=True)
                result = await execute_builtin_tool(bt.name, params, output_dir)
                return result.get("result", str(result)) if isinstance(result, dict) else str(result)

        tool = None
        if tool_id:
            tool = self.db.query(Tool).filter(Tool.tool_id == tool_id).first()
        elif tool_name:
            bindings = self.db.query(AgentToolBinding).filter(
                AgentToolBinding.agent_id == self.agent.agent_id
            ).all()
            for b in bindings:
                t = self.db.query(Tool).filter(Tool.tool_id == b.tool_id).first()
                if t and (t.name == tool_name or t.display_name == tool_name):
                    tool = t
                    break

        if not tool:
            raise ValueError(f"工具未找到: {tool_id or tool_name}")

        result = await tool_execution_service.execute_tool(
            tool, params, timeout_seconds=data.get("timeout_seconds", 60)
        )
        if isinstance(result, dict) and result.get("success"):
            return str(result.get("result", ""))
        raise ValueError(result.get("error", "工具执行失败") if isinstance(result, dict) else str(result))

    async def _run_hitl_node(
        self, node_id: str, data: Dict[str, Any], state: WorkflowState
    ) -> Dict[str, Any]:
        next_ids = self._get_next_node_ids(node_id)
        next_node_id = next_ids[0] if next_ids else None

        preview = self._resolve_template(
            data.get("preview_template") or "工作流执行到审批节点，请审核后继续。",
            state,
        )
        last_output = self._last_output(state)

        approval = HITLApproval(
            approval_id=gen_uuid(),
            session_id=self.session.session_id,
            agent_id=self.agent.agent_id,
            tool_name="__workflow_hitl__",
            tool_args={
                "node_id": node_id,
                "preview": preview,
                "last_output": last_output,
                "next_node_id": next_node_id,
            },
            status="PENDING",
        )
        self.db.add(approval)

        state.status = "hitl_wait"
        state.next_node_id = next_node_id
        state.current_node_id = node_id

        self.session.status = SessionStatus.HITL_WAIT
        self.session.pending_context = {
            "kind": "workflow",
            "workflow_state": state.to_dict(),
            "approval_id": approval.approval_id,
        }
        self.db.commit()

        record = NodeExecutionRecord(
            node_id=node_id, node_type="hitl",
            label=data.get("label", node_id), status="hitl_wait",
            output=preview[:500],
        )
        state.trace.append(record.to_dict())

        return {
            "hitl_pending": True,
            "approval_id": approval.approval_id,
            "next_node_id": next_node_id,
            "status": "hitl_wait",
            "output": preview,
        }

    async def _run_subgraph_node(self, data: Dict[str, Any], state: WorkflowState) -> tuple:
        from services.agent_service import agent_service

        child_id = data.get("child_agent_id")
        if not child_id:
            raise ValueError("子图节点未配置 child_agent_id")

        input_msg = self._resolve_template(
            data.get("input_template") or "{{input}}", state
        )

        child_session = SessionModel(
            session_id=gen_uuid(),
            agent_id=child_id,
            caller_type="AGENT",
            caller_id=self.agent.agent_id,
            token_budget=self.agent.token_budget,
            trace_id=self.trace_id,
        )
        self.db.add(child_session)
        self.db.flush()

        result = await agent_service.chat_with_agent(
            db=self.db,
            agent_id=child_id,
            session_id=child_session.session_id,
            message=input_msg,
            timeout_seconds=data.get("timeout_seconds", 120),
            execution_mode="auto",
            skip_history=True,
        )

        content = result.get("content", "")
        tokens = result.get("tokens_used", 0)
        return content, tokens

    async def _run_screenpilot_node(
        self, node_id: str, data: Dict[str, Any], state: WorkflowState
    ) -> Dict[str, Any]:
        """P2: ScreenPilot 工作流节点 — 直接调用驭屏服务。"""
        from services.screenpilot.config import SCREENPILOT_ENABLED

        if not SCREENPILOT_ENABLED:
            return {"status": "failed", "error": "ScreenPilot 未启用 (SCREENPILOT_ENABLED=false)"}

        from services.screenpilot.service import run_workflow_screenpilot

        params_raw = data.get("parameters") or data.get("params") or "{}"
        if isinstance(params_raw, str):
            params = json.loads(self._resolve_template(params_raw, state) or "{}")
        else:
            params = {k: self._resolve_template(str(v), state) for k, v in params_raw.items()}

        screen_session_id = self._resolve_template(
            data.get("screen_session_id") or state.variables.get("__screen_session_id__", ""),
            state,
        )
        operation = data.get("operation") or "navigate"

        result = await run_workflow_screenpilot(
            self.db,
            operation=operation,
            system_id=data.get("system_id") or "",
            screen_session_id=screen_session_id,
            skill_id=data.get("skill_id") or "",
            params=params,
            url=self._resolve_template(data.get("url") or "", state),
            action=data.get("action") or "click",
            target_ref=self._resolve_template(data.get("target_ref") or "", state),
            value=self._resolve_template(data.get("value") or "", state),
            vela_session_id=self.session.session_id,
            agent_id=self.agent.agent_id,
        )

        if result.get("screen_session_id"):
            state.variables["__screen_session_id__"] = result["screen_session_id"]

        if result.get("hitl_pending"):
            next_ids = self._get_next_node_ids(node_id)
            next_node_id = next_ids[0] if next_ids else None
            approval_id = result.get("approval_id", "")

            self.session.status = SessionStatus.HITL_WAIT
            self.session.pending_context = {
                "kind": "workflow",
                "workflow_state": state.to_dict(),
                "approval_id": approval_id,
                "screenpilot_node_id": node_id,
                "next_node_id": next_node_id,
            }
            state.status = "hitl_wait"
            state.next_node_id = next_node_id
            state.current_node_id = node_id
            self.db.commit()

            return {
                "hitl_pending": True,
                "approval_id": approval_id,
                "next_node_id": next_node_id,
                "status": "hitl_wait",
                "output": result.get("message", "ScreenPilot HITL 等待审批"),
            }

        if not result.get("success", True) and result.get("error"):
            return {"status": "failed", "error": result.get("error", "ScreenPilot 执行失败")}

        output = json.dumps(result, ensure_ascii=False)[:4000]
        return {"status": "success", "output": output}

    def _get_next_node_ids(self, node_id: str) -> List[str]:
        edges = self.compiled.adjacency.get(node_id, [])
        default_edges = [
            e for e in edges
            if e.get("sourceHandle", "default") in ("default", None, "")
        ]
        use_edges = default_edges or edges
        return [e.get("target") for e in use_edges if e.get("target")]

    def _get_condition_target(self, node_id: str, branch: str) -> Optional[str]:
        edges = self.compiled.adjacency.get(node_id, [])
        for e in edges:
            handle = e.get("sourceHandle", "default")
            if handle == branch or (branch == "true" and handle == "true") or (branch == "false" and handle == "false"):
                return e.get("target")
        for e in edges:
            if e.get("sourceHandle", "default") == "default":
                return e.get("target")
        return None

    def _eval_condition(self, expression: str, state: WorkflowState) -> str:
        """评估条件表达式，返回 true/false"""
        expr = self._resolve_template(expression, state).strip()
        if not expr:
            return "false"

        lower = expr.lower()
        if lower in ("true", "yes", "1"):
            return "true"
        if lower in ("false", "no", "0"):
            return "false"

        # contains "text"
        m = re.match(r'^(.+?)\s+contains\s+["\'](.+?)["\']$', expr, re.IGNORECASE)
        if m:
            left, needle = m.group(1).strip(), m.group(2)
            return "true" if needle in left else "false"

        # equals "text"
        m = re.match(r'^(.+?)\s+equals\s+["\'](.+?)["\']$', expr, re.IGNORECASE)
        if m:
            left, right = m.group(1).strip(), m.group(2)
            return "true" if left == right else "false"

        # regex "pattern"
        m = re.match(r'^(.+?)\s+regex\s+["\'](.+?)["\']$', expr, re.IGNORECASE)
        if m:
            left, pattern = m.group(1).strip(), m.group(2)
            try:
                return "true" if re.search(pattern, left) else "false"
            except re.error:
                return "false"

        return "true" if expr else "false"

    def _resolve_template(self, template: str, state: WorkflowState) -> str:
        if not template:
            return ""

        def replace_var(match):
            key = match.group(1).strip()
            if key == "input":
                return str(state.variables.get("__input__", state.input))
            if "." in key:
                node_id, field = key.split(".", 1)
                if field == "output":
                    return str(state.variables.get(node_id, ""))
            if key in state.variables:
                return str(state.variables[key])
            return match.group(0)

        result = re.sub(r"\{\{(.+?)\}\}", replace_var, template)
        return result

    def _resolve_output(self, template: Optional[str], state: WorkflowState) -> str:
        if not template:
            return ""
        return self._resolve_template(template, state)

    def _last_output(self, state: WorkflowState) -> str:
        for nid in reversed(list(state.variables.keys())):
            if nid != "__input__":
                return str(state.variables[nid])
        return str(state.variables.get("__input__", ""))

    def _audit(self, node_id: str, ntype: str, record: NodeExecutionRecord):
        log = AuditLog(
            log_id=gen_uuid(),
            agent_id=self.agent.agent_id,
            session_id=self.session.session_id,
            event_type="workflow_node",
            event_data={
                "node_id": node_id,
                "node_type": ntype,
                "status": record.status,
                "label": record.label,
                "output_preview": record.output[:200] if record.output else "",
            },
            duration_ms=record.duration_ms,
            trace_id=self.trace_id,
        )
        self.db.add(log)

    def _build_response(
        self,
        state: WorkflowState,
        pending_approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "success": state.status in ("completed", "hitl_wait"),
            "status": state.status,
            "result": state.final_result,
            "variables": state.variables,
            "trace": state.trace,
            "execution_trace": state.trace,
            "thinking_log": self.thinking_log,
            "total_tokens": state.total_tokens,
            "pending_approval_id": pending_approval_id,
            "workflow_state": state.to_dict(),
        }
