"""
HITL 人工审批路由
处理工具执行前的审批工单（SGL-CFG-06）和多 Agent 交付审批（MA-IMP-09）
"""
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import HITLApproval, Session as AgentSession, SessionStatus
from schemas import HITLApprovalResponse, HITLReview

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/sessions", tags=["hitl"])


@router.get("/{session_id}/pending-approvals", response_model=List[HITLApprovalResponse])
def get_pending_approvals(session_id: str, db: Session = Depends(get_db)):
    """获取待审批列表"""
    approvals = db.query(HITLApproval).filter(
        HITLApproval.session_id == session_id,
        HITLApproval.status == "PENDING",
    ).all()
    return approvals


@router.post("/{session_id}/approvals/{approval_id}/approve")
def approve_action(
    session_id: str,
    approval_id: str,
    payload: HITLReview,
    db: Session = Depends(get_db),
):
    """批准工具执行 / 多 Agent 交付

    SGL-CFG-06: 普通工具审批通过后，执行工具并把结果作为 system 消息注入 session.messages，
                前端可在收到响应后重新发起对话让 agent 基于工具结果继续推理。
    MA-IMP-09:  __delivery__ 审批通过后，把 final_result 作为 assistant 消息写入 session.messages。
    """
    approval = db.query(HITLApproval).filter(
        HITLApproval.approval_id == approval_id,
        HITLApproval.session_id == session_id,
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="审批工单不存在")
    if approval.status != "PENDING":
        raise HTTPException(status_code=400, detail="该工单已处理")

    approval.status = "APPROVED"
    approval.reviewer = payload.reviewer
    approval.review_comment = payload.comment
    approval.reviewed_at = datetime.now(timezone.utc)

    session = db.query(AgentSession).filter(
        AgentSession.session_id == session_id
    ).first()
    if session:
        session.status = SessionStatus.ACTIVE

    result_data = {"success": True, "message": "已批准", "tool_name": approval.tool_name}

    # WF-IMP-08: 工作流 HITL 审批
    if approval.tool_name == "__workflow_hitl__":
        result_data = _resume_workflow_after_hitl(db, session, approval, approved=True)
        db.commit()
        return result_data

    # MA-IMP-09: 多 Agent 交付审批
    if approval.tool_name == "__delivery__":
        tool_args = approval.tool_args or {}
        final_result = tool_args.get("final_result", "")
        if session:
            messages = session.messages or []
            messages.append({
                "role": "assistant",
                "content": final_result,
                "meta": {"approved": True, "approval_id": approval_id},
            })
            session.messages = messages
            session.pending_context = {}
        result_data["final_result"] = final_result
        result_data["kind"] = "delivery"
        db.commit()
        return result_data

    # ScreenPilot: ui_* 延迟动作审批通过后执行
    tool_args = approval.tool_args or {}
    if approval.tool_name.startswith("ui_") and tool_args.get("deferred"):
        tool_result_str = ""
        if session:
            from services.screenpilot.service import execute_deferred_ui_act
            tool_result_str = __import__("asyncio").run(
                execute_deferred_ui_act(db, approval)
            )
            messages = session.messages or []
            preview = tool_args.get("preview_payload") or {}
            messages.append({
                "role": "system",
                "content": f"[HITL 审批通过] ScreenPilot 工具 {approval.tool_name} 已执行，结果如下：\n{tool_result_str}",
                "meta": {"approved": True, "approval_id": approval_id, "preview_payload": preview},
            })
            session.messages = messages
            session.pending_context = {}
        db.commit()
        return {
            "success": True,
            "message": "已批准",
            "tool_name": approval.tool_name,
            "kind": "screenpilot",
            "tool_result": tool_result_str,
        }

    # SGL-CFG-06: 普通工具审批通过后执行工具
    if session:
        tool_args = approval.tool_args or {}
        tool_name = approval.tool_name
        tool_result_str = _execute_pending_tool(db, session, tool_name, tool_args)
        messages = session.messages or []
        messages.append({
            "role": "system",
            "content": f"[HITL 审批通过] 工具 {tool_name} 已执行，结果如下：\n{tool_result_str}",
            "meta": {"approved": True, "approval_id": approval_id},
        })
        session.messages = messages
        session.pending_context = {}

    db.commit()
    result_data["kind"] = "tool_call"
    return result_data


@router.post("/{session_id}/approvals/{approval_id}/reject")
def reject_action(
    session_id: str,
    approval_id: str,
    payload: HITLReview,
    db: Session = Depends(get_db),
):
    """拒绝工具执行 / 多 Agent 交付"""
    approval = db.query(HITLApproval).filter(
        HITLApproval.approval_id == approval_id,
        HITLApproval.session_id == session_id,
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="审批工单不存在")
    if approval.status != "PENDING":
        raise HTTPException(status_code=400, detail="该工单已处理")

    approval.status = "REJECTED"
    approval.reviewer = payload.reviewer
    approval.review_comment = payload.comment
    approval.reviewed_at = datetime.now(timezone.utc)

    session = db.query(AgentSession).filter(
        AgentSession.session_id == session_id
    ).first()
    if session:
        session.status = SessionStatus.ACTIVE
        messages = session.messages or []
        if approval.tool_name == "__workflow_hitl__":
            messages.append({
                "role": "system",
                "content": f"[HITL 审批拒绝] 工作流在节点 {approval.tool_args.get('node_id', '')} 被拒绝。原因：{payload.comment or '无'}",
                "meta": {"approved": False, "approval_id": approval_id},
            })
            session.pending_context = {}
        elif approval.tool_name == "__delivery__":
            messages.append({
                "role": "assistant",
                "content": f"⏸️ 多 Agent 任务的交付物被审批拒绝。\n拒绝人：{payload.reviewer or 'unknown'}\n拒绝原因：{payload.comment or '无'}",
                "meta": {"approved": False, "approval_id": approval_id},
            })
        else:
            messages.append({
                "role": "system",
                "content": f"[HITL 审批拒绝] 工具 {approval.tool_name} 调用被拒绝。原因：{payload.comment or '无'}。请基于此结果调整后续行动。",
                "meta": {"approved": False, "approval_id": approval_id},
            })
        session.messages = messages
        session.pending_context = {}

    db.commit()
    return {
        "success": True,
        "message": "已拒绝",
        "tool_name": approval.tool_name,
        "kind": "delivery" if approval.tool_name == "__delivery__" else (
            "workflow" if approval.tool_name == "__workflow_hitl__" else "tool_call"
        ),
    }


def _resume_workflow_after_hitl(db: Session, session, approval, approved: bool) -> dict:
    """WF-IMP-08: HITL 审批后恢复工作流执行"""
    import asyncio
    from models import Agent, ModelProvider, ModelService
    from services.workflow_engine import WorkflowEngine, WorkflowState
    from services.agent_service import AgentService

    pending = session.pending_context or {}
    wf_state_dict = pending.get("workflow_state") or {}

    agent = db.query(Agent).filter(Agent.agent_id == session.agent_id).first()
    if not agent:
        return {"success": False, "message": "Agent 不存在", "kind": "workflow"}

    model_svc = db.query(ModelService).filter(
        ModelService.model_service_id == agent.model_service_id
    ).first()
    provider = db.query(ModelProvider).filter(
        ModelProvider.provider_id == model_svc.provider_id
    ).first() if model_svc else None

    if not model_svc or not provider:
        return {"success": False, "message": "模型配置缺失", "kind": "workflow"}

    engine = WorkflowEngine(
        db=db, agent=agent, session=session,
        provider=provider, model_svc=model_svc,
    )
    wf_state = WorkflowState.from_dict(wf_state_dict)

    async def _run():
        return await engine.resume(wf_state, hitl_approved=approved)

    result = asyncio.run(_run())

    async def _finalize():
        return await AgentService._finalize_workflow_chat(db, session, "", result)

    response = asyncio.run(_finalize())

    return {
        "success": True,
        "message": "工作流已恢复执行" if approved else "工作流已终止",
        "tool_name": approval.tool_name,
        "kind": "workflow",
        "final_result": response.get("content", ""),
        "execution_trace": response.get("execution_trace", []),
        "pending_approval_id": response.get("pending_approval_id"),
        "pending_workflow": bool(response.get("pending_approval_id")),
    }


def _execute_pending_tool(db: Session, session: AgentSession, tool_name: str, tool_args: dict) -> str:
    """SGL-CFG-06: 审批通过后执行挂起的工具，返回结果字符串"""
    try:
        from models import Agent, AgentToolBinding, Tool
        from services.builtin_tools import BuiltinTool, BUILTIN_TOOLS, execute_builtin_tool

        agent = db.query(Agent).filter(Agent.agent_id == session.agent_id).first()
        if not agent:
            return f"工具执行失败：Agent 不存在"

        # 1. 内置工具
        for bt in BUILTIN_TOOLS:
            if bt.name == tool_name:
                output_dir = f"/tmp/vela_hitl_{session.session_id}"
                import os
                os.makedirs(output_dir, exist_ok=True)
                result = __import__("asyncio").run(execute_builtin_tool(tool_name, tool_args, output_dir))
                return result.get("result", str(result)) if isinstance(result, dict) else str(result)

        # 2. 自定义工具（含 MCP）
        bindings = db.query(AgentToolBinding).filter(
            AgentToolBinding.agent_id == agent.agent_id,
        ).all()
        tool_ids = [b.tool_id for b in bindings]
        tool = None
        for tid in tool_ids:
            t = db.query(Tool).filter(Tool.tool_id == tid, Tool.name == tool_name).first()
            if t:
                tool = t
                break
        if not tool:
            return f"工具 {tool_name} 未找到"

        from services.tool_service import tool_execution_service
        result = __import__("asyncio").run(
            tool_execution_service.execute_tool(tool, tool_args, timeout_seconds=60)
        )
        if isinstance(result, dict) and result.get("success"):
            return result.get("result", "")
        return f"工具执行错误: {result.get('error') if isinstance(result, dict) else result}"
    except Exception as e:
        logger.error(f"执行挂起工具失败: {e}", exc_info=True)
        return f"工具执行异常: {str(e)}"
