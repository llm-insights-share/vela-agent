"""
HITL 人工审批路由
处理工具执行前的审批工单（SGL-CFG-06）和多 Agent 交付审批（MA-IMP-09）
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from database import get_db
from models import HITLApproval, Session as AgentSession, SessionStatus, now_utc
from schemas import HITLApprovalResponse, HITLReview

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/sessions", tags=["hitl"])


def _parse_tool_result(tool_result_str: str) -> Dict[str, Any]:
    if not tool_result_str:
        return {}
    try:
        data = json.loads(tool_result_str)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _schedule_agent_resume_after_hitl(
    db: Session,
    session: AgentSession,
    *,
    reason: str,
    tool_result_str: str = "",
) -> str:
    """Kick agent chat on the uvicorn loop so the UI shows progress + final answer."""
    original_goal = ""
    for msg in session.messages or []:
        if msg.get("role") == "user" and (msg.get("content") or "").strip():
            original_goal = str(msg.get("content") or "").strip()
            break
    result_obj = _parse_tool_result(tool_result_str)
    skill_completed = bool(result_obj.get("skill_completed"))
    replayed = result_obj.get("replayed_steps")
    remaining = result_obj.get("remaining_steps") or []
    skill_name = result_obj.get("skill_name") or ""
    screen_sid = ""
    try:
        screen_sid = str(
            ((result_obj.get("results") or [{}])[0] or {}).get("screen_session_id")
            or ""
        )
    except Exception:
        screen_sid = ""
    # Prefer screen session from latest screenpilot system meta / tool args in history.
    if not screen_sid:
        for msg in reversed(session.messages or []):
            meta = msg.get("meta") or {}
            preview = meta.get("preview_payload") or {}
            if preview.get("skill_id") or meta.get("approved"):
                break

    resume_message = (
        "【系统·驭屏续跑】人工已批准 ScreenPilot/UI 技能相关操作。\n"
        f"原因: {reason}\n"
        f"技能: {skill_name or '(见上文工具结果)'}\n"
        f"本轮已重放步骤数: {replayed}\n"
        f"技能是否完成: {'是' if skill_completed else '否'}；剩余步骤: {remaining}\n"
        f"用户原任务：{original_goal or '（见会话上文）'}\n\n"
        "请立刻使用驭屏工具（cu_observe / cu_act / cu_replay_skill 等）继续完成用户原任务："
        "先观察当前页面状态，再执行未完成操作；不要过早结束。"
        "若页面已达成目标，再给出简洁最终结论。"
    )
    session.status = SessionStatus.RUNNING
    pending = dict(session.pending_context or {})
    pending["background_job"] = {
        "started_at": now_utc().isoformat(),
        "message_preview": f"HITL 续跑: {reason}"[:120],
        "agent_id": session.agent_id,
        "hitl_resume": True,
    }
    session.pending_context = pending
    flag_modified(session, "pending_context")
    session.last_active_at = now_utc()
    db.commit()

    from routes.sessions import _run_session_chat_background

    asyncio.create_task(
        _run_session_chat_background(
            session.session_id,
            {
                "message": resume_message,
                "attachment_ids": [],
                "skill_pack_id": None,
                "timeout_seconds": None,
                "execution_mode": "react",
                "skip_history": False,
            },
        ),
        name=f"session-hitl-resume-{session.session_id}",
    )
    return "RUNNING"


def _finalize_screenpilot_hitl_session(
    db: Session,
    session: Optional[AgentSession],
    *,
    tool_result_str: str,
    reason: str,
) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
    """Return (session_status, pending_approval_id, preview_payload)."""
    if not session:
        return "ACTIVE", None, None
    result_obj = _parse_tool_result(tool_result_str)
    if result_obj.get("hitl_pending") and result_obj.get("approval_id"):
        session.status = SessionStatus.HITL_WAIT
        session.last_active_at = now_utc()
        # Attach new pending approval onto latest assistant if present.
        messages = list(session.messages or [])
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                msg["pendingApprovalId"] = result_obj.get("approval_id")
                msg["pendingToolName"] = reason
                if result_obj.get("preview_payload"):
                    msg["previewPayload"] = result_obj.get("preview_payload")
                msg["approvalStatus"] = None
                break
        session.messages = messages
        flag_modified(session, "messages")
        db.commit()
        return (
            "HITL_WAIT",
            str(result_obj.get("approval_id")),
            result_obj.get("preview_payload") or {},
        )
    status = _schedule_agent_resume_after_hitl(
        db, session, reason=reason, tool_result_str=tool_result_str
    )
    return status, None, None


@router.get("/{session_id}/pending-approvals", response_model=List[HITLApprovalResponse])
def get_pending_approvals(session_id: str, db: Session = Depends(get_db)):
    """获取待审批列表"""
    approvals = db.query(HITLApproval).filter(
        HITLApproval.session_id == session_id,
        HITLApproval.status == "PENDING",
    ).all()
    return approvals


@router.post("/{session_id}/approvals/{approval_id}/approve")
async def approve_action(
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
        result_data = await _resume_workflow_after_hitl(db, session, approval, approved=True)
        if session and (session.caller_type or "").upper() == "SCHEDULE":
            from services.schedule.runner import sync_schedule_run_from_session
            sync_schedule_run_from_session(db, session.session_id)
        db.commit()
        return result_data

    # MA-IMP-09: 多 Agent 交付审批
    if approval.tool_name == "__delivery__":
        tool_args = approval.tool_args or {}
        final_result = tool_args.get("final_result", "") or ""
        # Fallback if tool_args lost the payload but pending_context still has it
        if not str(final_result).strip() and session:
            pending = session.pending_context or {}
            if isinstance(pending, dict):
                final_result = pending.get("final_result") or final_result
        if session:
            # Copy list so SQLAlchemy detects JSON mutation
            messages = list(session.messages or [])
            # Merge deliverable into the same gate bubble (single chat bubble UX).
            # Keep thinking / executionStory; do not append a second assistant message.
            for m in messages:
                pid = m.get("pendingApprovalId") or m.get("pending_approval_id")
                if pid != approval_id:
                    continue
                prev_content = (m.get("content") or "").strip()
                if not m.get("hitlGateNotice") and prev_content:
                    m["hitlGateNotice"] = prev_content
                m["approvalStatus"] = "approved"
                m["pendingDelivery"] = True
                m["content"] = final_result or "（交付内容为空）"
                m.pop("approvalFinalResult", None)
            session.messages = messages
            flag_modified(session, "messages")
            session.pending_context = {}
            flag_modified(session, "pending_context")
        result_data["final_result"] = final_result
        result_data["kind"] = "delivery"
        if session and (session.caller_type or "").upper() == "SCHEDULE":
            from services.schedule.runner import sync_schedule_run_from_session
            sync_schedule_run_from_session(db, session.session_id)
        db.commit()
        return result_data

    # ScreenPilot 登录验证码 HITL
    tool_args = approval.tool_args or {}
    if approval.tool_name == "cu_login_otp" or tool_args.get("flow_kind") == "otp_wait":
        otp_code = (payload.otp_code or payload.comment or "").strip()
        if not otp_code:
            raise HTTPException(status_code=400, detail="请提供验证码")

        tool_result_str = ""
        if session:
            from services.screenpilot.service import resume_login_after_otp_approval
            tool_result_str = await resume_login_after_otp_approval(db, approval, otp_code)
            messages = session.messages or []
            preview = tool_args.get("preview_payload") or {}
            messages.append({
                "role": "system",
                "content": f"[HITL 验证码已提交] ScreenPilot 登录继续执行，结果如下：\n{tool_result_str}",
                "meta": {"approved": True, "approval_id": approval_id, "preview_payload": preview},
            })
            session.messages = messages
            flag_modified(session, "messages")
            session.pending_context = {}
        if session and (session.caller_type or "").upper() == "SCHEDULE":
            from services.schedule.runner import sync_schedule_run_from_session
            sync_schedule_run_from_session(db, session.session_id)
        session_status, pending_aid, pending_preview = _finalize_screenpilot_hitl_session(
            db, session, tool_result_str=tool_result_str, reason="otp"
        )
        out = {
            "success": True,
            "message": "验证码已提交，会话继续执行",
            "tool_name": approval.tool_name,
            "kind": "screenpilot_otp",
            "tool_result": tool_result_str,
            "session_status": session_status,
        }
        if pending_aid:
            out["pending_approval_id"] = pending_aid
            out["preview_payload"] = pending_preview or {}
            out["message"] = "验证码已提交，仍有待审批步骤"
        return out

    # ScreenPilot 技能缺参追问 HITL
    if approval.tool_name == "cu_skill_params" or tool_args.get("flow_kind") == "skill_params":
        param_values = payload.param_values if isinstance(payload.param_values, dict) else {}
        if not param_values and (payload.comment or "").strip():
            # allow comment as JSON fallback
            try:
                parsed = json.loads(payload.comment)
                if isinstance(parsed, dict):
                    param_values = parsed
            except Exception:
                pass
        missing = list(tool_args.get("missing_params") or [])
        still = [k for k in missing if not str(param_values.get(k) or "").strip()]
        if still:
            raise HTTPException(status_code=400, detail=f"请填写参数: {', '.join(still)}")

        tool_result_str = ""
        if session:
            from services.screenpilot.service import resume_skill_after_params_approval
            tool_result_str = await resume_skill_after_params_approval(db, approval, param_values)
            messages = session.messages or []
            preview = tool_args.get("preview_payload") or {}
            messages.append({
                "role": "system",
                "content": (
                    f"[HITL 技能参数已提交] 已合并参数 {list(param_values.keys())}，"
                    f"重放结果如下：\n{tool_result_str}"
                ),
                "meta": {"approved": True, "approval_id": approval_id, "preview_payload": preview},
            })
            session.messages = messages
            flag_modified(session, "messages")
            session.pending_context = {}
        if session and (session.caller_type or "").upper() == "SCHEDULE":
            from services.schedule.runner import sync_schedule_run_from_session
            sync_schedule_run_from_session(db, session.session_id)
        session_status, pending_aid, pending_preview = _finalize_screenpilot_hitl_session(
            db, session, tool_result_str=tool_result_str, reason="skill_params"
        )
        out = {
            "success": True,
            "message": "技能参数已提交，会话继续执行",
            "tool_name": approval.tool_name,
            "kind": "screenpilot_skill_params",
            "tool_result": tool_result_str,
            "session_status": session_status,
        }
        if pending_aid:
            out["pending_approval_id"] = pending_aid
            out["preview_payload"] = pending_preview or {}
            out["message"] = "参数已提交，仍有待审批步骤"
        return out

    # ScreenPilot: cu_*（兼容历史 ui_*）延迟动作审批通过后执行
    tool_args = approval.tool_args or {}
    if approval.tool_name.startswith(("cu_", "ui_")) and tool_args.get("deferred"):
        pending = (session.pending_context or {}) if session else {}
        is_workflow = pending.get("kind") == "workflow"

        tool_result_str = ""
        if session:
            from services.screenpilot.service import execute_deferred_ui_act
            # Must await on the same event loop as Playwright sessions (no asyncio.run).
            tool_result_str = await execute_deferred_ui_act(db, approval)

            if is_workflow:
                result_data = await _resume_workflow_after_hitl(db, session, approval, approved=True)
                result_data["tool_result"] = tool_result_str
                result_data["kind"] = "workflow"
                if session and (session.caller_type or "").upper() == "SCHEDULE":
                    from services.schedule.runner import sync_schedule_run_from_session
                    sync_schedule_run_from_session(db, session.session_id)
                db.commit()
                return result_data

            messages = session.messages or []
            preview = tool_args.get("preview_payload") or {}
            messages.append({
                "role": "system",
                "content": f"[HITL 审批通过] ScreenPilot 工具 {approval.tool_name} 已执行，结果如下：\n{tool_result_str}",
                "meta": {"approved": True, "approval_id": approval_id, "preview_payload": preview},
            })
            session.messages = messages
            flag_modified(session, "messages")
            session.pending_context = {}

        # Close duplicate PENDING tickets for the same skill step.
        if (tool_args.get("skill_id") or tool_args.get("step_id")) and session_id:
            siblings = (
                db.query(HITLApproval)
                .filter(
                    HITLApproval.session_id == session_id,
                    HITLApproval.status == "PENDING",
                    HITLApproval.tool_name == approval.tool_name,
                    HITLApproval.approval_id != approval_id,
                )
                .all()
            )
            for sib in siblings:
                sargs = sib.tool_args or {}
                if (
                    sargs.get("skill_id") == tool_args.get("skill_id")
                    and (
                        sargs.get("step_id") == tool_args.get("step_id")
                        or sargs.get("resume_from_step") == tool_args.get("resume_from_step")
                    )
                ):
                    sib.status = "REJECTED"
                    sib.reviewer = payload.reviewer or "system"
                    sib.review_comment = f"superseded by {approval_id}"
                    sib.reviewed_at = datetime.now(timezone.utc)

        if session and (session.caller_type or "").upper() == "SCHEDULE":
            from services.schedule.runner import sync_schedule_run_from_session
            sync_schedule_run_from_session(db, session.session_id)

        session_status, pending_aid, pending_preview = _finalize_screenpilot_hitl_session(
            db, session, tool_result_str=tool_result_str, reason=approval.tool_name
        )
        out = {
            "success": True,
            "message": "已批准，会话继续执行" if session_status == "RUNNING" else "已批准",
            "tool_name": approval.tool_name,
            "kind": "screenpilot",
            "tool_result": tool_result_str,
            "session_status": session_status,
        }
        if pending_aid:
            out["pending_approval_id"] = pending_aid
            out["preview_payload"] = pending_preview or {}
            out["message"] = "已批准，仍有待审批步骤"
        return out

    # SGL-CFG-06: 普通工具审批通过后执行工具
    if session:
        tool_args = approval.tool_args or {}
        tool_name = approval.tool_name
        tool_result_str = await asyncio.to_thread(
            _execute_pending_tool, db, session, tool_name, tool_args
        )
        messages = session.messages or []
        messages.append({
            "role": "system",
            "content": f"[HITL 审批通过] 工具 {tool_name} 已执行，结果如下：\n{tool_result_str}",
            "meta": {"approved": True, "approval_id": approval_id},
        })
        session.messages = messages
        session.pending_context = {}

    db.commit()
    if session and (session.caller_type or "").upper() == "SCHEDULE":
        from services.schedule.runner import sync_schedule_run_from_session
        sync_schedule_run_from_session(db, session.session_id)
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
        messages = list(session.messages or [])
        if approval.tool_name == "__workflow_hitl__":
            messages.append({
                "role": "system",
                "content": f"[HITL 审批拒绝] 工作流在节点 {approval.tool_args.get('node_id', '')} 被拒绝。原因：{payload.comment or '无'}",
                "meta": {"approved": False, "approval_id": approval_id},
            })
        elif approval.tool_name == "__delivery__":
            # Keep a single bubble: mark gate rejected in place (preserve process story).
            reject_text = (
                f"⏸️ 多 Agent 任务的交付物被审批拒绝。\n"
                f"拒绝人：{payload.reviewer or 'unknown'}\n"
                f"拒绝原因：{payload.comment or '无'}"
            )
            for m in messages:
                pid = m.get("pendingApprovalId") or m.get("pending_approval_id")
                if pid != approval_id:
                    continue
                prev_content = (m.get("content") or "").strip()
                if not m.get("hitlGateNotice") and prev_content:
                    m["hitlGateNotice"] = prev_content
                m["approvalStatus"] = "rejected"
                m["pendingDelivery"] = True
                m["content"] = reject_text
        else:
            messages.append({
                "role": "system",
                "content": f"[HITL 审批拒绝] 工具 {approval.tool_name} 调用被拒绝。原因：{payload.comment or '无'}。请基于此结果调整后续行动。",
                "meta": {"approved": False, "approval_id": approval_id},
            })
        from sqlalchemy.orm.attributes import flag_modified
        session.messages = messages
        flag_modified(session, "messages")
        session.pending_context = {}
        flag_modified(session, "pending_context")

    db.commit()
    if session and (session.caller_type or "").upper() == "SCHEDULE":
        from services.schedule.runner import sync_schedule_run_from_session
        sync_schedule_run_from_session(db, session.session_id)
    return {
        "success": True,
        "message": "已拒绝",
        "tool_name": approval.tool_name,
        "kind": "delivery" if approval.tool_name == "__delivery__" else (
            "workflow" if approval.tool_name == "__workflow_hitl__" else "tool_call"
        ),
    }


async def _resume_workflow_after_hitl(db: Session, session, approval, approved: bool) -> dict:
    """WF-IMP-08: HITL 审批后恢复工作流执行"""
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

    result = await engine.resume(wf_state, hitl_approved=approved)
    response = await AgentService._finalize_workflow_chat(db, session, "", result)

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
