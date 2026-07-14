import asyncio
import json
import re
import os
import shutil
import hashlib
import traceback
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from models import (
    Agent, AgentVersion, AgentStatus, VersionStatus, ChangeType, AgentType,
    AgentSkillBinding, AgentKnowledgeBinding, AgentToolBinding,
    Session as SessionModel, ModelService, ModelProvider, SessionStatus,
    SkillPack, SkillPackStatus, KnowledgeBase, Tool, ToolStatus, ToolType,
    gen_uuid, now_utc
)
from schemas import AgentCreate, AgentUpdate, ValidationResult
from services.builtin_tools import (
    BuiltinTool, BUILTIN_TOOLS, build_builtin_openai_tool_def, execute_builtin_tool,
)


class AgentLoopError(Exception):
    pass


class TokenBudgetExceededError(AgentLoopError):
    pass


class MaxIterationsExceededError(AgentLoopError):
    pass


class HITLPendingError(AgentLoopError):
    """SGL-CFG-06 / MA-IMP-09: 工具调用或交付物需人工审批，循环挂起"""
    def __init__(self, approval_id: str, tool_name: str, message: str = ""):
        self.approval_id = approval_id
        self.tool_name = tool_name
        super().__init__(message or f"工具 [{tool_name}] 等待人工审批 (approval_id={approval_id})")


class AgentService:

    @staticmethod
    def validate_agent(db: Session, agent_id: str) -> ValidationResult:
        result = ValidationResult()
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not agent:
            result.errors.append({"field": "agent_id", "message": "Agent 不存在"})
            result.passed = False
            return result

        model_svc = db.query(ModelService).filter(
            ModelService.model_service_id == agent.model_service_id
        ).first()
        if not model_svc:
            result.errors.append({"field": "model_service_id", "message": "模型服务不存在"})
        elif model_svc.status.value != "ACTIVE":
            result.errors.append({"field": "model_service_id", "message": f"模型服务状态异常: {model_svc.status.value}"})

        if agent.max_concurrent_sessions < 1:
            result.errors.append({"field": "max_concurrent_sessions", "message": "最大并发会话数必须 ≥ 1"})

        if agent.token_budget < 1000:
            result.errors.append({"field": "token_budget", "message": "Token 预算必须 ≥ 1000"})

        if not agent.system_prompt or not agent.system_prompt.strip():
            result.warnings.append({"field": "system_prompt", "message": "System Prompt 为空"})
        elif len(agent.system_prompt) > 32000:
            result.warnings.append({"field": "system_prompt", "message": "System Prompt 超过 32000 字符"})

        if agent.autonomy_level == "L1":
            has_hitl = any(
                v == "ask_first" for v in (agent.tool_permissions or {}).values()
            )
            if not has_hitl:
                result.warnings.append({
                    "field": "autonomy_level",
                    "message": "L1 级别建议配置 HITL 审批通道（tool_permissions 中设置 ask_first）"
                })

        for skill_binding in db.query(AgentSkillBinding).filter(
            AgentSkillBinding.agent_id == agent_id
        ).all():
            skill = db.query(SkillPack).filter(
                SkillPack.skill_pack_id == skill_binding.skill_pack_id
            ).first()
            if not skill or skill.status.value not in ("ACTIVE",):
                result.warnings.append({
                    "field": "skill_pack_ids",
                    "message": f"Skill 包 {skill_binding.skill_pack_id} 不可用"
                })

        for kb_binding in db.query(AgentKnowledgeBinding).filter(
            AgentKnowledgeBinding.agent_id == agent_id
        ).all():
            kb = db.query(KnowledgeBase).filter(
                KnowledgeBase.kb_id == kb_binding.kb_id
            ).first()
            if not kb or kb.status.value not in ("ACTIVE",):
                result.warnings.append({
                    "field": "knowledge_base_ids",
                    "message": f"知识库 {kb_binding.kb_id} 不可用"
                })

        result.passed = len(result.errors) == 0

        # WF: 工作流图校验
        if agent.agent_type == AgentType.WORKFLOW:
            from services.workflow_compiler import WorkflowCompiler
            wf_result = WorkflowCompiler.validate(db, agent.workflow_definition or {})
            for err in wf_result.get("errors", []):
                result.errors.append(err)
            for warn in wf_result.get("warnings", []):
                result.warnings.append(warn)
            if wf_result.get("errors"):
                result.passed = False

        return result

    @staticmethod
    def create_agent(db: Session, data: AgentCreate) -> Agent:
        agent_type = AgentType(data.agent_type) if data.agent_type else AgentType.SINGLE
        agent = Agent(
            agent_id=gen_uuid(),
            name=data.name,
            description=data.description,
            model_service_id=data.model_service_id,
            system_prompt=data.system_prompt,
            dept_id=data.dept_id,
            autonomy_level=data.autonomy_level,
            max_concurrent_sessions=data.max_concurrent_sessions,
            token_budget=data.token_budget,
            tool_permissions=data.tool_permissions,
            tags=data.tags,
            status=AgentStatus.DRAFT,
            agent_type=agent_type,
            composition_config=data.composition_config or {},
            workflow_definition=data.workflow_definition or {},
            max_iterations=data.max_iterations,
            step_timeout_seconds=data.step_timeout_seconds,
            tool_retry_count=data.tool_retry_count,
            tool_retry_backoff=data.tool_retry_backoff,
            allow_repeat_tool_calls=data.allow_repeat_tool_calls,
            max_repeat_threshold=data.max_repeat_threshold,
            single_call_token_limit=data.single_call_token_limit,
        )
        db.add(agent)
        db.flush()

        snapshot = {
            "name": data.name,
            "description": data.description,
            "model_service_id": data.model_service_id,
            "system_prompt": data.system_prompt,
            "dept_id": data.dept_id,
            "autonomy_level": data.autonomy_level,
            "max_concurrent_sessions": data.max_concurrent_sessions,
            "token_budget": data.token_budget,
            "tool_permissions": data.tool_permissions,
            "tags": data.tags,
            "max_iterations": data.max_iterations,
            "step_timeout_seconds": data.step_timeout_seconds,
            "tool_retry_count": data.tool_retry_count,
            "tool_retry_backoff": data.tool_retry_backoff,
            "allow_repeat_tool_calls": data.allow_repeat_tool_calls,
            "max_repeat_threshold": data.max_repeat_threshold,
            "single_call_token_limit": data.single_call_token_limit,
            "agent_type": agent_type.value,
            "composition_config": data.composition_config or {},
            "workflow_definition": data.workflow_definition or {},
        }
        version = AgentVersion(
            version_id=gen_uuid(),
            agent_id=agent.agent_id,
            version="0.1.0-draft",
            version_seq=1,
            change_type=ChangeType.MINOR,
            change_summary="初始创建",
            snapshot=snapshot,
            status=VersionStatus.DRAFT,
        )
        db.add(version)
        db.flush()

        agent.current_version_id = version.version_id

        for sp_id in (data.skill_pack_ids or []):
            skill = db.query(SkillPack).filter(SkillPack.skill_pack_id == sp_id).first()
            if skill:
                binding = AgentSkillBinding(
                    agent_id=agent.agent_id,
                    skill_pack_id=sp_id,
                    tool_permissions=data.tool_permissions or {},
                )
                db.add(binding)

        for kb_id in (data.knowledge_base_ids or []):
            kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
            if kb:
                binding = AgentKnowledgeBinding(
                    agent_id=agent.agent_id,
                    kb_id=kb_id,
                )
                db.add(binding)

        for tid in (data.tool_ids or []):
            tool = db.query(Tool).filter(Tool.tool_id == tid).first()
            if tool:
                binding = AgentToolBinding(
                    agent_id=agent.agent_id,
                    tool_id=tid,
                    permission="allowed",
                )
                db.add(binding)

        # SGL-CFG-06: 若提供 tool_bindings，则覆盖上面的 tool_ids 写入（含 require_approval）
        if data.tool_bindings:
            # 先清除刚才按 tool_ids 写入的（避免重复）
            db.query(AgentToolBinding).filter(
                AgentToolBinding.agent_id == agent.agent_id
            ).delete()
            for b in data.tool_bindings:
                tool = db.query(Tool).filter(Tool.tool_id == b.tool_id).first()
                if tool:
                    binding = AgentToolBinding(
                        agent_id=agent.agent_id,
                        tool_id=b.tool_id,
                        permission="allowed",
                        require_approval=bool(b.require_approval),
                    )
                    db.add(binding)

        db.commit()
        db.refresh(agent)
        return agent

    @staticmethod
    def update_agent(db: Session, agent_id: str, data: AgentUpdate) -> Optional[Agent]:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not agent:
            return None

        update_fields = data.model_dump(exclude_unset=True, exclude={"skill_pack_ids", "knowledge_base_ids", "tool_ids", "tool_bindings", "change_summary"})
        change_summary = data.change_summary or "配置修改"

        for key, value in update_fields.items():
            if hasattr(agent, key):
                if key == "agent_type" and value is not None:
                    value = AgentType(value)
                setattr(agent, key, value)

        last_version = db.query(AgentVersion).filter(
            AgentVersion.agent_id == agent_id
        ).order_by(AgentVersion.version_seq.desc()).first()

        last_seq = last_version.version_seq if last_version else 0
        last_ver = last_version.version if last_version else "0.0.0"

        parts = last_ver.replace("-draft", "").split(".")
        if data.model_service_id or data.autonomy_level:
            change_type = ChangeType.MAJOR
            new_ver = f"{int(parts[0]) + 1}.0.0"
        elif data.system_prompt or data.skill_pack_ids or data.knowledge_base_ids:
            change_type = ChangeType.MINOR
            new_ver = f"{parts[0]}.{int(parts[1]) + 1}.0"
        else:
            change_type = ChangeType.PATCH
            new_ver = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"

        if agent.status == AgentStatus.DRAFT:
            new_ver += "-draft"

        snapshot = {
            "name": agent.name,
            "description": agent.description,
            "model_service_id": agent.model_service_id,
            "system_prompt": agent.system_prompt,
            "dept_id": agent.dept_id,
            "autonomy_level": agent.autonomy_level,
            "max_concurrent_sessions": agent.max_concurrent_sessions,
            "token_budget": agent.token_budget,
            "tool_permissions": agent.tool_permissions,
            "tags": agent.tags,
            "max_iterations": agent.max_iterations,
            "step_timeout_seconds": agent.step_timeout_seconds,
            "tool_retry_count": agent.tool_retry_count,
            "tool_retry_backoff": agent.tool_retry_backoff,
            "allow_repeat_tool_calls": agent.allow_repeat_tool_calls,
            "max_repeat_threshold": agent.max_repeat_threshold,
            "single_call_token_limit": agent.single_call_token_limit,
            "agent_type": agent.agent_type.value if agent.agent_type else "SINGLE",
            "composition_config": agent.composition_config or {},
            "workflow_definition": agent.workflow_definition or {},
        }
        version = AgentVersion(
            version_id=gen_uuid(),
            agent_id=agent_id,
            version=new_ver,
            version_seq=last_seq + 1,
            change_type=change_type,
            change_summary=change_summary,
            snapshot=snapshot,
            status=VersionStatus.DRAFT,
        )
        db.add(version)
        db.flush()
        agent.current_version_id = version.version_id

        if data.skill_pack_ids is not None:
            db.query(AgentSkillBinding).filter(
                AgentSkillBinding.agent_id == agent_id
            ).delete()
            for sp_id in data.skill_pack_ids:
                skill = db.query(SkillPack).filter(SkillPack.skill_pack_id == sp_id).first()
                if skill:
                    binding = AgentSkillBinding(
                        agent_id=agent_id,
                        skill_pack_id=sp_id,
                        tool_permissions=(data.tool_permissions or agent.tool_permissions or {}),
                    )
                    db.add(binding)

        if data.knowledge_base_ids is not None:
            db.query(AgentKnowledgeBinding).filter(
                AgentKnowledgeBinding.agent_id == agent_id
            ).delete()
            for kb_id in data.knowledge_base_ids:
                kb = db.query(KnowledgeBase).filter(KnowledgeBase.kb_id == kb_id).first()
                if kb:
                    binding = AgentKnowledgeBinding(agent_id=agent_id, kb_id=kb_id)
                    db.add(binding)

        if data.tool_ids is not None:
            db.query(AgentToolBinding).filter(
                AgentToolBinding.agent_id == agent_id
            ).delete()
            for tid in data.tool_ids:
                tool = db.query(Tool).filter(Tool.tool_id == tid).first()
                if tool:
                    binding = AgentToolBinding(
                        agent_id=agent_id,
                        tool_id=tid,
                        permission="allowed",
                    )
                    db.add(binding)

        # SGL-CFG-06: 若提供 tool_bindings，则覆盖上面的 tool_ids 更新（含 require_approval）
        if data.tool_bindings is not None:
            db.query(AgentToolBinding).filter(
                AgentToolBinding.agent_id == agent_id
            ).delete()
            for b in data.tool_bindings:
                tool = db.query(Tool).filter(Tool.tool_id == b.tool_id).first()
                if tool:
                    binding = AgentToolBinding(
                        agent_id=agent_id,
                        tool_id=b.tool_id,
                        permission="allowed",
                        require_approval=bool(b.require_approval),
                    )
                    db.add(binding)

        db.commit()
        db.refresh(agent)
        return agent

    @staticmethod
    def publish_agent(db: Session, agent_id: str, version_id: Optional[str] = None) -> Optional[Agent]:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not agent:
            return None

        target_version_id = version_id or agent.current_version_id
        version = db.query(AgentVersion).filter(
            AgentVersion.version_id == target_version_id
        ).first()
        if not version:
            return None

        version.status = VersionStatus.PUBLISHED
        version.version = version.version.replace("-draft", "")
        agent.status = AgentStatus.PUBLISHED
        agent.current_version_id = version.version_id

        db.commit()
        db.refresh(agent)
        return agent

    @staticmethod
    async def _finalize_workflow_chat(
        db: Session,
        session: SessionModel,
        message: str,
        result: Dict[str, Any],
        persist_user_message: bool = True,
    ) -> Dict[str, Any]:
        """WF: 统一处理工作流 chat 响应与 session 写入"""
        messages = session.messages or []
        if persist_user_message and message and message.strip():
            messages.append({"role": "user", "content": message})

        pending_approval_id = result.get("pending_approval_id")
        status = result.get("status", "")

        if status == "completed" and not pending_approval_id:
            messages.append({"role": "assistant", "content": result.get("result", "")})
            session.pending_context = {}
            session.status = SessionStatus.ACTIVE
        elif pending_approval_id:
            session.status = SessionStatus.HITL_WAIT

        session.messages = messages
        session.token_used = (session.token_used or 0) + result.get("total_tokens", 0)
        session.last_active_at = now_utc()
        db.commit()

        if pending_approval_id:
            preview = ""
            for t in reversed(result.get("trace") or []):
                if t.get("node_type") == "hitl":
                    preview = t.get("output", "")
                    break
            return {
                "content": f"⏸️ 工作流执行到 HITL 审批节点，等待人工审批。\n审批工单 ID: `{pending_approval_id}`\n\n{preview}",
                "thinking": "\n".join(result.get("thinking_log", [])),
                "tokens_used": result.get("total_tokens", 0),
                "total_tokens": session.token_used or 0,
                "execution_mode": "hitl_pending",
                "execution_trace": result.get("execution_trace", []),
                "files": [],
                "pending_approval_id": pending_approval_id,
                "pending_workflow": True,
                "session_status": "HITL_WAIT",
            }

        if status == "failed":
            return {
                "content": f"❌ 工作流执行失败：{result.get('result', '未知错误')}",
                "thinking": "\n".join(result.get("thinking_log", [])),
                "tokens_used": result.get("total_tokens", 0),
                "total_tokens": session.token_used or 0,
                "execution_mode": "workflow",
                "execution_trace": result.get("execution_trace", []),
                "files": [],
            }

        return {
            "content": result.get("result", ""),
            "thinking": "\n".join(result.get("thinking_log", [])),
            "tokens_used": result.get("total_tokens", 0),
            "total_tokens": session.token_used or 0,
            "execution_mode": "workflow",
            "execution_trace": result.get("execution_trace", []),
            "files": [],
        }

    @staticmethod
    def finalize_background_chat(
        db: Session,
        session: SessionModel,
        result: Dict[str, Any],
    ) -> None:
        """后台任务完成后：合并响应元数据到 messages 并更新会话状态。"""
        from sqlalchemy.orm.attributes import flag_modified

        messages = list(session.messages or [])
        pending_approval_id = result.get("pending_approval_id")
        session_status = result.get("session_status")
        success = result.get("success", True)
        content = result.get("content", "")

        if messages and messages[-1].get("role") == "user" and content:
            messages.append({"role": "assistant", "content": content})
        elif content and not messages:
            messages.append({"role": "assistant", "content": content})

        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            if result.get("thinking"):
                msg["thinking"] = result["thinking"]
            if result.get("execution_trace"):
                msg["executionTrace"] = result["execution_trace"]
            if result.get("execution_mode"):
                msg["executionMode"] = result["execution_mode"]
            if result.get("active_skill"):
                msg["activeSkill"] = result["active_skill"]
            if result.get("files"):
                msg["files"] = result["files"]
            if result.get("files_truncated"):
                msg["filesTruncated"] = True
            if pending_approval_id:
                msg["pendingApprovalId"] = pending_approval_id
            if result.get("pending_delivery"):
                msg["pendingDelivery"] = True
            if result.get("pending_workflow"):
                msg["pendingWorkflow"] = True
            if result.get("pending_tool_name"):
                msg["pendingToolName"] = result["pending_tool_name"]
            if result.get("preview_payload"):
                msg["previewPayload"] = result["preview_payload"]
            if result.get("pending_otp"):
                msg["pendingOtp"] = True
            break

        session.messages = messages
        flag_modified(session, "messages")

        if pending_approval_id or session_status == "HITL_WAIT":
            session.status = SessionStatus.HITL_WAIT
        elif result.get("aborted"):
            session.status = SessionStatus.ACTIVE
        elif success is False:
            session.status = SessionStatus.ERROR
        else:
            session.status = SessionStatus.ACTIVE

        pending = dict(session.pending_context or {})
        pending.pop("background_job", None)
        session.pending_context = pending
        session.last_active_at = now_utc()
        db.commit()

        try:
            from services.session_abort import clear_abort

            clear_abort(session.session_id)
        except Exception:
            pass

    @staticmethod
    async def chat_with_agent(
        db: Session,
        agent_id: str,
        session_id: str,
        message: str,
        skill_pack_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        execution_mode: Optional[str] = "auto",
        skip_history: bool = False,
        persist_user_message: bool = True,
    ) -> Dict[str, Any]:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not agent:
            raise ValueError("Agent 不存在")

        model_svc = db.query(ModelService).filter(
            ModelService.model_service_id == agent.model_service_id
        ).first()
        if not model_svc:
            raise ValueError("模型服务不存在")

        provider = db.query(ModelProvider).filter(
            ModelProvider.provider_id == model_svc.provider_id
        ).first()
        if not provider:
            raise ValueError("模型供应商不存在")

        session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id
        ).first()
        if not session:
            raise ValueError("会话不存在")

        from services.session_abort import clear_abort

        clear_abort(session_id)

        from models import AgentType

        # WF: 工作流恢复（HITL 审批后由前端触发 resume 或 chat 空消息）
        pending_ctx = session.pending_context or {}
        if (
            agent.agent_type == AgentType.WORKFLOW
            and pending_ctx.get("kind") == "workflow"
            and pending_ctx.get("workflow_resume")
        ):
            from services.workflow_engine import WorkflowEngine, WorkflowState
            wf_state = WorkflowState.from_dict(pending_ctx.get("workflow_state") or {})
            engine = WorkflowEngine(
                db=db, agent=agent, session=session,
                provider=provider, model_svc=model_svc,
            )
            result = await asyncio.wait_for(
                engine.resume(wf_state, hitl_approved=True),
                timeout=float(timeout_seconds) if timeout_seconds else 300.0,
            )
            return await AgentService._finalize_workflow_chat(
                db, session, message, result, persist_user_message=persist_user_message
            )

        # MA: 如果是 COMPOSITE 类型，走 CoordinatorEngine
        if agent.agent_type == AgentType.COMPOSITE:
            from services.coordinator_service import CoordinatorEngine
            coordinator = CoordinatorEngine(
                db=db,
                parent_agent=agent,
                session=session,
                provider=provider,
                model_svc=model_svc,
            )
            result = await asyncio.wait_for(
                coordinator.run(message),
                timeout=float(timeout_seconds) if timeout_seconds else 300.0,
            )
            # 写入 session 消息历史（HITL 挂起时不写 final_result，留待审批通过后再写）
            messages = session.messages or []
            if persist_user_message:
                messages.append({"role": "user", "content": message})
            pending_approval_id = result.get("pending_approval_id")
            if not pending_approval_id:
                messages.append({"role": "assistant", "content": result.get("result", "")})
            session.messages = messages
            session.token_used = (session.token_used or 0) + result.get("total_tokens", 0)
            session.last_active_at = now_utc()
            db.commit()

            # MA-IMP-09: 交付前 HITL Gate 触发时返回挂起响应
            if pending_approval_id:
                return {
                    "content": f"⏸️ 多 Agent 任务已完成，但 Coordinator 触发了交付前 HITL Gate。\n审批工单 ID: `{pending_approval_id}`\n\n请在审批中心通过后查看最终交付物。",
                    "thinking": "\n".join(result.get("thinking_log", [])),
                    "tokens_used": result.get("total_tokens", 0),
                    "total_tokens": (session.token_used or 0),
                    "execution_mode": "hitl_pending",
                    "files": [],
                    "audit_trail": result.get("audit_trail", []),
                    "dispatch_count": result.get("dispatch_count", 0),
                    "pending_approval_id": pending_approval_id,
                    "pending_delivery": True,
                    "session_status": "HITL_WAIT",
                }

            return {
                "content": result.get("result", ""),
                "thinking": "\n".join(result.get("thinking_log", [])),
                "tokens_used": result.get("total_tokens", 0),
                "total_tokens": (session.token_used or 0),
                "execution_mode": "multi_agent",
                "files": [],
                "audit_trail": result.get("audit_trail", []),
                "dispatch_count": result.get("dispatch_count", 0),
            }

        # WF: 工作流型 Agent
        if agent.agent_type == AgentType.WORKFLOW:
            from services.workflow_engine import WorkflowEngine
            engine = WorkflowEngine(
                db=db, agent=agent, session=session,
                provider=provider, model_svc=model_svc,
            )
            result = await asyncio.wait_for(
                engine.run(message),
                timeout=float(timeout_seconds) if timeout_seconds else 300.0,
            )
            return await AgentService._finalize_workflow_chat(
                db, session, message, result, persist_user_message=persist_user_message
            )

        original_message = message
        rewrite_meta = None
        if getattr(agent, "query_rewrite_enabled", False):
            try:
                from services.query_rewrite import QueryRewriteEngine

                kb_ids = [
                    b.kb_id
                    for b in db.query(AgentKnowledgeBinding).filter(
                        AgentKnowledgeBinding.agent_id == agent_id
                    ).all()
                ]
                engine = QueryRewriteEngine(db=db, provider=provider, model_svc=model_svc)
                rewrite_result = await engine.rewrite(
                    message,
                    messages=session.messages or [],
                    agent_id=agent.agent_id,
                    user_id=session.caller_id or "",
                    memory_enabled=bool(getattr(agent, "memory_enabled", False)),
                    kb_ids=kb_ids,
                )
                rewrite_meta = rewrite_result.to_dict()
                rewrite_meta["_summary"] = rewrite_result.summary_line()
                if rewrite_result.need_clarification and rewrite_result.clarification:
                    # 记忆锚定无法确定时直接澄清，避免硬造检索式
                    messages = session.messages or []
                    if persist_user_message:
                        messages.append({"role": "user", "content": original_message})
                    messages.append({"role": "assistant", "content": rewrite_result.clarification})
                    session.messages = messages
                    session.last_active_at = now_utc()
                    db.commit()
                    return {
                        "content": rewrite_result.clarification,
                        "thinking": rewrite_result.summary_line(),
                        "tokens_used": rewrite_result.tokens_used,
                        "total_tokens": (session.token_used or 0) + rewrite_result.tokens_used,
                        "execution_mode": "query_rewrite_clarify",
                        "rewrite": rewrite_meta,
                        "files": [],
                    }
                message = rewrite_result.query_for_downstream
            except Exception as e:
                print(f"[AgentService] Query改写失败，使用原文: {e}")
                rewrite_meta = {
                    "original": original_message,
                    "rewritten": original_message,
                    "tier": 0,
                    "method": "pass_through",
                    "fallback_reason": f"engine_error:{e}",
                }

        knowledge_context = ""
        kb_bindings = db.query(AgentKnowledgeBinding).filter(
            AgentKnowledgeBinding.agent_id == agent_id
        ).all()
        if kb_bindings:
            try:
                from services.knowledge_service import knowledge_service as ks
                kb_parts = []
                for binding in kb_bindings:
                    results = ks.search(binding.kb_id, message, top_k=3)
                    for r in results:
                        kb_parts.append(r["content"])
                if kb_parts:
                    knowledge_context = "\n\n参考知识库内容：\n" + "\n---\n".join(kb_parts)
            except Exception as e:
                print(f"[AgentService] 知识库搜索失败，跳过: {e}")

        skill_context = ""
        active_skill_name = None
        if skill_pack_id:
            skill = db.query(SkillPack).filter(
                SkillPack.skill_pack_id == skill_pack_id,
                SkillPack.status == SkillPackStatus.ACTIVE,
            ).first()
            if skill:
                skill_context = f"\n\n你需要使用以下 Skill 来处理用户请求：\n## Skill: {skill.name}\n{skill.skill_content or skill.description}"
                active_skill_name = skill.name
        else:
            skill_bindings = db.query(AgentSkillBinding).filter(
                AgentSkillBinding.agent_id == agent_id
            ).all()
            if skill_bindings:
                skill_parts = []
                for binding in skill_bindings:
                    skill = db.query(SkillPack).filter(
                        SkillPack.skill_pack_id == binding.skill_pack_id,
                        SkillPack.status == SkillPackStatus.ACTIVE,
                    ).first()
                    if not skill:
                        continue

                    relevance = _compute_skill_relevance(message, skill)
                    if relevance > 0.15:
                        skill_parts.append(f"## Skill: {skill.name}\n{skill.skill_content or skill.description}")

                if skill_parts:
                    skill_context = "\n\n你可以使用以下 Skill 来处理用户请求：\n" + "\n\n".join(skill_parts)

        tool_bindings = db.query(AgentToolBinding).filter(
            AgentToolBinding.agent_id == agent_id
        ).all()
        # If agent already uses ScreenPilot, ensure newly added cu_* (e.g. cu_vision) are registered+bound.
        try:
            from services.screenpilot.config import is_screenpilot_enabled
            from services.screenpilot.mcp_tools import ensure_cu_tools_registered_and_bound

            if is_screenpilot_enabled() and tool_bindings:
                bound_names = []
                for tb in tool_bindings:
                    t0 = db.query(Tool).filter(Tool.tool_id == tb.tool_id).first()
                    if t0:
                        bound_names.append(t0.name)
                if any(n.startswith("cu_") for n in bound_names):
                    ensure_cu_tools_registered_and_bound(db)
                    tool_bindings = db.query(AgentToolBinding).filter(
                        AgentToolBinding.agent_id == agent_id
                    ).all()
        except Exception as _e:

        available_tools = []
        for tb in tool_bindings:
            tool = db.query(Tool).filter(
                Tool.tool_id == tb.tool_id,
                Tool.status == ToolStatus.ACTIVE,
            ).first()
            if tool:
                available_tools.append(tool)


        available_tools.extend(BUILTIN_TOOLS)

        has_tools = len(available_tools) > 0
        has_kb = len(kb_bindings) > 0
        has_skills = bool(skill_context)

        mode = execution_mode or "auto"
        if mode == "auto":
            mode = _analyze_execution_mode(message, has_tools, has_kb, has_skills)
            # OTP codes typed into chat must keep tools so agent can fill & submit.
            if (
                has_tools
                and mode == "direct"
                and _looks_like_otp_message(original_message)
                and _session_has_screenpilot_context(session)
            ):
                mode = "react"
                # Expand for LLM only; history still stores original_message via AgentLoop.
                message = (
                    f"用户提供了登录验证码：{(original_message or '').strip()}。"
                    "请立即调用 cu_observe 查看当前页面，将验证码填入验证码输入框，"
                    "然后点击登录按钮完成登录。必须调用工具，不要只回复文字。"
                )

        loop = AgentLoop(
            db=db,
            agent=agent,
            session=session,
            provider=provider,
            model_svc=model_svc,
            available_tools=available_tools,
            timeout_seconds=timeout_seconds,
            user_message=message,
            original_user_message=original_message,
            active_skill_name=active_skill_name,
            knowledge_context=knowledge_context,
            skill_context=skill_context,
            skip_history=skip_history,
        )
        if rewrite_meta:
            loop.thinking_log.append(
                rewrite_meta.get("_summary")
                or f"[QueryRewrite] T{rewrite_meta.get('tier')}/{rewrite_meta.get('method')} "
                   f"score={rewrite_meta.get('score', 0):.2f}"
            )
            if rewrite_meta.get("rewritten") and rewrite_meta.get("rewritten") != original_message:
                loop.thinking_log.append(
                    f"  原文: {original_message[:120]}\n  改写: {str(rewrite_meta.get('rewritten'))[:200]}"
                )

        try:
            result = await loop.run(mode)
            if rewrite_meta:
                result["rewrite"] = rewrite_meta
                rewrite_tokens = int(rewrite_meta.get("tokens_used") or 0)
                if rewrite_tokens:
                    result["tokens_used"] = (result.get("tokens_used") or 0) + rewrite_tokens
            return result
        except HITLPendingError as he:
            # SGL-CFG-06 / ScreenPilot GOV: 工具需人工审批，返回挂起响应
            preview_payload = {}
            try:
                from models import HITLApproval
                approval = loop.db.query(HITLApproval).filter(
                    HITLApproval.approval_id == he.approval_id
                ).first()
                if approval and approval.tool_args:
                    preview_payload = approval.tool_args.get("preview_payload") or {}
                    if not preview_payload and approval.tool_name == "cu_login_otp":
                        preview_payload = {
                            "flow_kind": "otp_wait",
                            "prompt": approval.tool_args.get("prompt") or "请输入短信验证码",
                        }
            except Exception:
                pass
            if he.tool_name == "cu_login_otp" or preview_payload.get("flow_kind") == "otp_wait":
                prompt = preview_payload.get("prompt") or "请输入短信验证码"
                hitl_content = (
                    f"⏸️ 登录需要验证码：{prompt}\n"
                    f"审批工单 ID: `{he.approval_id}`\n\n"
                    "请在对话下方输入验证码并提交。"
                )
            else:
                hitl_content = (
                    f"⏸️ 工具 [{he.tool_name}] 需要人工审批后才能继续执行。\n"
                    f"审批工单 ID: `{he.approval_id}`\n\n"
                    "请在审批中心处理后继续对话。"
                )
            hitl_result = {
                "content": hitl_content,
                "thinking": "\n".join(loop.thinking_log) if loop else "",
                "tokens_used": 0,
                "total_tokens": session.token_used or 0,
                "execution_mode": "hitl_pending",
                "files": [],
                "pending_approval_id": he.approval_id,
                "pending_tool_name": he.tool_name,
                "preview_payload": preview_payload,
                "pending_otp": he.tool_name == "cu_login_otp"
                or preview_payload.get("flow_kind") == "otp_wait",
                "session_status": "HITL_WAIT",
            }
            if rewrite_meta:
                hitl_result["rewrite"] = rewrite_meta
            return hitl_result
        except Exception as e:
            traceback.print_exc()
            if loop and getattr(loop, "memory_enabled", False):
                loop._memory_record_exception(str(e))
            thinking_log = loop.thinking_log if loop else []
            return {
                "success": False,
                "error": str(e),
                "content": str(e),
                "thinking_log": thinking_log,
                "files": [],
            }


class AgentLoop:
    MAX_CONTEXT_MESSAGES = 50
    SKILL_MAX_CHARS = 8000

    def __init__(
        self,
        db: Session,
        agent,
        session,
        provider,
        model_svc,
        available_tools: list,
        timeout_seconds: Optional[int],
        user_message: str,
        active_skill_name: Optional[str],
        knowledge_context: str,
        skill_context: str,
        skip_history: bool = False,
        original_user_message: Optional[str] = None,
    ):
        self.db = db
        self.agent = agent
        self.session = session
        self.provider = provider
        self.model_svc = model_svc
        self.available_tools = available_tools
        self.timeout_seconds = timeout_seconds
        self.user_message = user_message
        # 会话历史保存原文；LLM / 检索使用可能已改写的 user_message
        self.original_user_message = (
            original_user_message if original_user_message is not None else user_message
        )
        self.active_skill_name = active_skill_name
        self.knowledge_context = knowledge_context
        self.skill_context = skill_context
        self.skip_history = skip_history
        self.thinking_log: List[str] = []
        self.total_tokens_used = 0
        self.generated_files: List[Dict[str, str]] = []

        # SGL-CFG-02: ReAct 最大迭代次数（可配置）
        self.max_iterations = agent.max_iterations or 10
        # SGL-CFG-03: 单步超时时间
        self.step_timeout = agent.step_timeout_seconds or 60
        # SGL-CFG-04: 工具失败重试次数与退避策略
        self.tool_retry_count = agent.tool_retry_count if agent.tool_retry_count is not None else 2
        self.tool_retry_backoff = agent.tool_retry_backoff or "fixed"
        # SGL-CFG-05: 防死循环配置
        self.allow_repeat_tool_calls = agent.allow_repeat_tool_calls if agent.allow_repeat_tool_calls is not None else True
        self.max_repeat_threshold = agent.max_repeat_threshold or 3
        # SGL-CFG-07: 单次调用 Token 上限
        self.single_call_token_limit = agent.single_call_token_limit or 8192

        # SGL-IMP-03: 死循环检测历史
        self._tool_call_history: List[str] = []
        self._screenpilot_session_ids: set = set()

        # SGL-CFG-06: 加载工具→require_approval 映射
        self.tool_require_approval: Dict[str, bool] = {}
        for b in db.query(AgentToolBinding).filter(
            AgentToolBinding.agent_id == agent.agent_id
        ).all():
            if b.require_approval:
                self.tool_require_approval[b.tool_id] = True

        # 记忆闭环：仅当 Agent 挂载记忆模块时启用
        self.memory_enabled = bool(getattr(agent, "memory_enabled", False))
        self._memory_context = ""
        if self.memory_enabled:
            try:
                from services.memory.retriever import SelfRetriever
                retriever = SelfRetriever(db)
                parts = []
                # 每轮重建 system prompt，持续注入偏好与近期摘要
                parts.append(retriever.on_session_start(
                    agent_id=agent.agent_id,
                    user_id=session.caller_id or "",
                ))
                if available_tools:
                    parts.append(retriever.before_tool_invoke(
                        agent_id=agent.agent_id,
                        tool_names=[t.name for t in available_tools],
                    ))
                self._memory_context = "".join(p for p in parts if p)
            except Exception as e:
                print(f"[AgentLoop] 记忆检索失败，跳过: {e}")

        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "outputs", session.session_id
        )
        os.makedirs(self.output_dir, exist_ok=True)

    async def run(self, mode: str) -> Dict[str, Any]:
        total_timeout = float(self.timeout_seconds) if self.timeout_seconds else 300.0
        try:
            result = await asyncio.wait_for(
                self._run_inner(mode),
                timeout=total_timeout,
            )
            return result
        except asyncio.TimeoutError:
            self.thinking_log.append(f"[TIMEOUT] 整体执行超时（{total_timeout}s）")
            return self._build_result(
                f"任务执行超时（{total_timeout}s）。请尝试简化 Skill 内容或增加超时时间。",
                "\n".join(self.thinking_log),
                mode,
            )

    async def _run_inner(self, mode: str) -> Dict[str, Any]:
        if mode == "direct":
            return await self._run_direct()
        elif mode == "react" and self.available_tools:
            return await self._run_react()
        elif mode == "plan_and_execute" and (self.available_tools or self.knowledge_context):
            return await self._run_plan_and_execute()
        else:
            return await self._run_direct()

    def _build_system_prompt(self) -> str:
        system_prompt = self.agent.system_prompt or "你是一个智能助手。"
        # 注入当前日期，避免模型将「今天」误判为错误年份
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        weekday = weekday_map[datetime.now().weekday()]
        system_prompt += (
            f"\n\n当前日期：{today}（星期{weekday}）。"
            "理解「今天/本周/本月/今年」时必须以该日期为准；"
            "搜索新闻或时效信息时，查询关键词应使用正确的公历年份，不要使用过时年份。"
        )
        if self.knowledge_context:
            system_prompt += self.knowledge_context
        if self.skill_context:
            truncated = self.skill_context
            if len(truncated) > self.SKILL_MAX_CHARS:
                truncated = truncated[:self.SKILL_MAX_CHARS] + "\n\n[Skill 内容过长，已截断，请关注核心指令]"
            system_prompt += truncated
        if self._memory_context:
            system_prompt += self._memory_context
        return system_prompt

    def _build_initial_messages(self) -> List[Dict[str, Any]]:
        messages = [{"role": "system", "content": self._build_system_prompt()}]

        if not self.skip_history:
            history = self.session.messages or []
            for msg in history[-self.MAX_CONTEXT_MESSAGES:]:
                messages.append(msg)

        last_msg = messages[-1] if messages else None
        already_has_user = (
            last_msg
            and last_msg.get("role") == "user"
            and last_msg.get("content") == self.original_user_message
        )
        if already_has_user:
            if self.user_message != self.original_user_message:
                messages[-1] = {"role": "user", "content": self.user_message}
        else:
            messages.append({"role": "user", "content": self.user_message})
        return messages

    def _build_history_with_user(self, extra_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        history = list(self.session.messages or [])
        if not (
            history
            and history[-1].get("role") == "user"
            and history[-1].get("content") == self.original_user_message
        ):
            history.append({"role": "user", "content": self.original_user_message})
        return history + extra_messages

    def _truncate_context(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(messages) <= self.MAX_CONTEXT_MESSAGES + 1:
            return messages

        system_msg = messages[0]
        recent = messages[-(self.MAX_CONTEXT_MESSAGES):]

        tool_ids_seen = set()
        orphan_tool_messages = []
        for msg in reversed(recent):
            if msg.get("role") == "tool":
                tool_ids_seen.add(msg.get("tool_call_id", ""))
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if tc.get("id") not in tool_ids_seen:
                        orphan_tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "[工具结果已截断]",
                        })

        truncated = [system_msg] + orphan_tool_messages + recent
        return truncated

    def _check_token_budget(self, estimated_tokens: int):
        current = self.session.token_used or 0
        budget = self.session.token_budget or self.agent.token_budget
        if current + estimated_tokens + self.total_tokens_used > budget:
            self.thinking_log.append(
                f"[WARNING] Token 预算超限: 已用 {current + self.total_tokens_used}, 预算 {budget}，继续执行"
            )

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            total_chars += len(content)
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    total_chars += len(tc.get("function", {}).get("arguments", ""))
        return max(1, total_chars // 3)

    async def _call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        from services.model_provider import model_provider_service

        # SGL-CFG-07: 单次调用 Token 上限
        effective_max_tokens = max_tokens or min(
            self.agent.token_budget - (self.session.token_used or 0) - self.total_tokens_used,
            self.single_call_token_limit,
        )
        if effective_max_tokens < 1024:
            effective_max_tokens = 1024

        self._check_token_budget(self._estimate_tokens(messages) + effective_max_tokens)

        self.thinking_log.append(f"[LLM 调用] {len(messages)} 条消息, max_tokens={effective_max_tokens}")


        completion = await model_provider_service.chat_completion(
            provider=self.provider,
            model_name=self.model_svc.model_name,
            messages=messages,
            max_tokens=effective_max_tokens,
            tools=tools,
            timeout_seconds=self.timeout_seconds,
        )

        usage = completion.get("usage", {})
        self.total_tokens_used += usage.get("total_tokens", 0)
        return completion

    def _parse_tool_calls(self, msg: Dict[str, Any]) -> List[Dict[str, Any]]:
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            return tool_calls

        content = msg.get("content", "")
        parsed = self._parse_structured_output(content)
        if parsed:
            return [{
                "id": f"call_{gen_uuid()[:8]}",
                "type": "function",
                "function": {
                    "name": parsed["tool_name"],
                    "arguments": json.dumps(parsed["arguments"], ensure_ascii=False),
                },
            }]

        return []

    def _parse_structured_output(self, content: str) -> Optional[Dict[str, Any]]:
        if not content:
            return None

        json_match = re.search(r'```json\s*\n?(.*?)\n?```', content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict) and "tool_name" in data:
                    return data
                if isinstance(data, dict) and "function" in data:
                    return data["function"]
            except json.JSONDecodeError:
                pass

        json_match = re.search(r'\{[^{}]*"tool_name"\s*:\s*"[^"]+"[^{}]*\}', content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "tool_name" in data:
                    return data
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _safe_parse_tool_args(args_str: str) -> dict:
        if not args_str:
            return {}
        try:
            return json.loads(args_str)
        except json.JSONDecodeError:
            pass

        repaired = args_str.rstrip()
        if not repaired.endswith("}"):
            brace_depth = 0
            for ch in repaired:
                if ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
            repaired += "}" * max(0, brace_depth)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

        try:
            import re as _re
            result = {}
            str_pat = r'"([^"\\]*(?:\\.[^"\\]*)*)"'
            for m in _re.finditer(rf'"({str_pat})"\s*:\s*({str_pat})', repaired):
                key = m.group(2)
                val = m.group(4)
                try:
                    result[key] = json.loads(f'"{val}"')
                except json.JSONDecodeError:
                    result[key] = val
            if result:
                return result
        except Exception:
            pass

        return {}

    def _compact_tool_result_for_llm(self, tool_name: str, result_str: str) -> str:
        """Strip large binary fields before feeding ScreenPilot tool JSON back to the LLM."""
        if not result_str:
            return result_str
        text = result_str if isinstance(result_str, str) else str(result_str)
        if not text.lstrip().startswith("{"):
            return text[:12000] if len(text) > 12000 else text
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text[:12000] if len(text) > 12000 else text
        if not isinstance(data, dict):
            return text[:12000] if len(text) > 12000 else text

        for key in ("screenshot_b64", "som_image_b64", "screenshot", "image_b64"):
            if key in data and data[key]:
                data[key] = f"[omitted {len(str(data[key]))} chars]"

        elements = data.get("elements")
        if isinstance(elements, list) and len(elements) > 40:
            data["elements"] = elements[:40]
            data["elements_truncated"] = True

        compact = json.dumps(data, ensure_ascii=False)
        if tool_name in ("cu_search_skills", "ui_search_skills") and isinstance(
            data.get("items"), list
        ) and data["items"]:
            compact += (
                "\n[Hint] 命中 UI 技能后请优先调用 cu_replay_skill(skill_id, screen_session_id)；"
                "登录步骤中的 {{username}}/{{password}} 会自动使用系统凭证库，勿用聊天里的明文密码 cu_act。"
            )
        if len(compact) > 16000:
            compact = compact[:16000] + "…[truncated]"
        return compact

    @staticmethod
    def _parse_screenpilot_blocker(tool_result: str) -> Optional[Dict[str, Any]]:
        """Parse structured ScreenPilot risk_blocked / no-effect failures from tool JSON."""
        if not tool_result or not isinstance(tool_result, str):
            return None
        text = tool_result
        data = None
        if text.lstrip().startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
        if not isinstance(data, dict):
            try:
                outer = json.loads(text)
                if isinstance(outer, dict) and isinstance(outer.get("result"), str):
                    data = json.loads(outer["result"])
            except Exception:
                data = None
        if not isinstance(data, dict):
            return None
        if data.get("risk_blocked"):
            return {
                "error_code": str(data.get("error_code") or "RISK_BLOCK"),
                "url": str(data.get("url") or ""),
                "warning": str(data.get("warning") or ""),
                "recovery_hint": str(data.get("recovery_hint") or ""),
                "kind": "risk_blocked",
            }
        if data.get("executed") and data.get("effect_ok") is False:
            return {
                "error_code": "NO_EFFECT",
                "url": str((data.get("observe") or {}).get("url") or data.get("url") or ""),
                "warning": str(data.get("warning") or "动作已执行但未检测到 UI 变化"),
                "recovery_hint": (
                    "请更换目标控件、确认前置条件，或改用 login_macro / value=text=/css="
                ),
                "kind": "no_effect",
            }
        return None

    def _check_dead_loop(self, tool_name: str, args: dict) -> bool:
        """SGL-IMP-03: 死循环检测 - 连续N次调用同一工具且参数相同时强制中断"""
        if not self.allow_repeat_tool_calls:
            return False
        call_sig = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        self._tool_call_history.append(call_sig)
        if len(self._tool_call_history) < self.max_repeat_threshold:
            return False
        recent = self._tool_call_history[-self.max_repeat_threshold:]
        if len(set(recent)) == 1:
            self.thinking_log.append(
                f"[死循环检测] 连续 {self.max_repeat_threshold} 次调用 [{tool_name}] 且参数相同，强制中断"
            )
            return True
        return False

    def _is_sqlite_mcp_tool(self, tool) -> bool:
        if getattr(tool, "name", "") == "query_sqlite":
            return True
        if getattr(tool, "tool_type", None) != ToolType.MCP:
            return False
        config = tool.config or {}
        blob = json.dumps(config, ensure_ascii=False).lower()
        return "sqlite" in blob or "mcp-server-sqlite" in blob

    def _should_assess_tool_result(self, tool) -> bool:
        if getattr(tool, "name", "") == "nl2sql_query":
            return False
        return self._is_sqlite_mcp_tool(tool)

    def _heuristic_question_sql_mismatch(self, question: str, tool_args: Dict[str, Any]) -> Optional[str]:
        sql = (tool_args.get("query") or tool_args.get("question") or "").strip()
        if not sql:
            return None
        low_sql = sql.lower()
        if not (low_sql.startswith("select") or low_sql.startswith("with")):
            return None

        from_tables = re.findall(r"\bfrom\s+([a-zA-Z0-9_\.]+)", low_sql)
        join_tables = re.findall(r"\bjoin\s+([a-zA-Z0-9_\.]+)", low_sql)
        tables = {t.split(".")[-1].lower() for t in from_tables + join_tables}
        if not tables:
            return None

        q = question or ""
        q_low = q.lower()
        asks_customer = any(x in q for x in ("客户", "顾客")) or "customer" in q_low
        asks_product = any(x in q for x in ("产品", "商品")) or "product" in q_low

        customer_tables = {"customer", "customers", "client", "clients", "user", "users"}
        product_tables = {"product", "products", "sku", "item", "items", "goods"}

        if asks_customer and (tables & product_tables) and not (tables & customer_tables):
            return f"SQL 查询表 {sorted(tables)} 与问题中的「客户」语义不匹配"
        if asks_product and (tables & customer_tables) and not (tables & product_tables):
            return f"SQL 查询表 {sorted(tables)} 与问题中的「产品」语义不匹配"
        return None

    async def _assess_tool_result_satisfies_question(
        self, tool_name: str, tool_result: str, tool_args: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        question = (self.user_message or "").strip()
        if not question or not tool_result:
            return {"satisfied": True, "reason": "skip-empty"}

        tool_args = tool_args or {}
        heuristic_reason = self._heuristic_question_sql_mismatch(question, tool_args)
        if heuristic_reason:
            return {"satisfied": False, "reason": heuristic_reason}

        from services.model_provider import model_provider_service

        prompt = (
            "你是工具结果质检员。判断「工具返回」是否已包含足够事实数据来回答「用户问题」。\n"
            "必须结合工具调用参数（尤其是 SQL）判断查询对象是否与用户问题一致。\n"
            "仅返回表名/表结构、报错信息、或查询了错误业务对象（如问客户却查产品），均视为未满足。\n\n"
            f"用户问题：{question}\n"
            f"工具名称：{tool_name}\n"
            f"工具调用参数：{json.dumps(tool_args, ensure_ascii=False)[:1500]}\n"
            f"工具返回：\n{tool_result[:3500]}\n\n"
            '只输出 JSON：{"satisfied": true或false, "reason": "一句话原因"}'
        )
        try:
            completion = await model_provider_service.chat_completion(
                provider=self.provider,
                model_name=self.model_svc.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                timeout_seconds=min(30, self.step_timeout or 60),
            )
            content = (
                completion.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                data = json.loads(m.group())
                return {
                    "satisfied": bool(data.get("satisfied")),
                    "reason": str(data.get("reason", "")),
                }
        except Exception as exc:
            return {"satisfied": True, "reason": f"assess-skipped:{exc}"}
        return {"satisfied": True, "reason": "assess-parse-failed"}

    async def _finalize_tool_success(
        self, tool, args: Dict[str, Any], result: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not result.get("success") or not self._should_assess_tool_result(tool):
            return result

        preview = result.get("result", "") or ""
        assessment = await self._assess_tool_result_satisfies_question(
            tool.name, preview, tool_args=args
        )

        if assessment.get("satisfied"):
            return result

        self.thinking_log.append(
            f"  工具 [{tool.name}] 结果质检未通过: {assessment.get('reason', '')[:200]}"
        )
        fallback = await self._try_nl2sql_fallback(tool, args)
        if fallback and fallback.get("success"):
            self.thinking_log.append("  质检失败后已通过 nl2sql_query 重新查询")
            return fallback

        return {
            "success": False,
            "error": (
                f"工具返回未满足用户问题: {assessment.get('reason', '')}"
                f"；原始返回: {preview[:500]}"
            ),
        }

    def _resolve_nl2sql_question(self, args: Dict[str, Any]) -> str:
        explicit = (args.get("question") or "").strip()
        if explicit:
            return explicit
        raw = (args.get("query") or "").strip()
        if raw and not raw.lower().startswith(("select", "with")):
            return raw
        return (self.user_message or "").strip()

    async def _try_nl2sql_fallback(self, failed_tool, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._is_sqlite_mcp_tool(failed_tool):
            return None
        nl2sql_tool = next((t for t in self.available_tools if t.name == "nl2sql_query"), None)
        if not nl2sql_tool:
            return None
        question = self._resolve_nl2sql_question(args)
        if not question:
            return None

        from services.tool_service import tool_execution_service

        self.thinking_log.append(
            f"  SQLite 工具 [{failed_tool.name}] 失败，自动切换 nl2sql_query 分析: {question[:120]}"
        )
        return await tool_execution_service.execute_tool(
            nl2sql_tool,
            {"question": question, "session_id": self.session.session_id},
            timeout_seconds=self.step_timeout,
        )

    def _check_screenpilot_hitl_pending(self, tool, result: Dict[str, Any]) -> Optional[str]:
        """ScreenPilot MCP 返回 hitl_pending 时挂起 ReAct 循环。"""
        name = getattr(tool, "name", "") or ""
        if not name.startswith(("cu_", "ui_")) or not result.get("success"):
            return None
        raw = result.get("result", "")
        if not isinstance(raw, str):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if payload.get("hitl_pending") and payload.get("approval_id"):
            return payload["approval_id"]
        return None

    def _track_screenpilot_session(self, tool_result: Any) -> None:
        """Collect screen_session_id from cu_* results and backfill vela_session_id."""
        raw = tool_result
        if isinstance(raw, dict):
            payload = raw
        elif isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return
        else:
            return
        sid = (payload.get("screen_session_id") or "").strip()
        if not sid and isinstance(payload.get("observe"), dict):
            sid = (payload["observe"].get("screen_session_id") or "").strip()
        if not sid:
            return
        self._screenpilot_session_ids.add(sid)
        try:
            from models import ScreenSession
            row = (
                self.db.query(ScreenSession)
                .filter(ScreenSession.screen_session_id == sid)
                .first()
            )
            if row and not (row.vela_session_id or "").strip():
                row.vela_session_id = self.session.session_id
                if not (row.agent_id or "").strip():
                    row.agent_id = getattr(self.agent, "agent_id", "") or ""
                self.db.commit()
        except Exception:
            pass

    async def _execute_tool_with_retry(self, tool, args: Dict[str, Any]) -> Dict[str, Any]:
        # ScreenPilot：注入会话关联，便于轨迹自动编译回落 UI 技能库
        tool_name = getattr(tool, "name", "") or ""
        if tool_name.startswith(("cu_", "ui_")):
            args = dict(args or {})
            if not args.get("vela_session_id"):
                args["vela_session_id"] = self.session.session_id
            if not args.get("agent_id"):
                args["agent_id"] = getattr(self.agent, "agent_id", "") or ""

        # SGL-CFG-06: HITL 拦截 - 工具调用前检查 require_approval
        tool_id = getattr(tool, "tool_id", None) or tool.name
        if self.tool_require_approval.get(tool_id):
            approval = self._create_hitl_approval(
                tool_name=tool.name,
                tool_args=args,
                pending_kind="tool_call",
            )
            self.thinking_log.append(
                f"  工具 [{tool.name}] 触发 HITL 审批 (approval_id={approval.approval_id})，循环挂起"
            )
            raise HITLPendingError(approval.approval_id, tool.name)

        result: Dict[str, Any]
        if isinstance(tool, BuiltinTool):
            try:
                result = await execute_builtin_tool(tool.name, args, self.output_dir)
            except Exception as e:
                result = {"success": False, "error": f"内置工具执行失败: {str(e)}"}
            self._memory_record_tool(tool.name, args, result)
            return result

        from services.tool_service import tool_execution_service

        last_error = None
        for attempt in range(self.tool_retry_count + 1):
            try:
                result = await tool_execution_service.execute_tool(
                    tool, args, timeout_seconds=self.step_timeout
                )
                sp_approval = self._check_screenpilot_hitl_pending(tool, result)
                if sp_approval:
                    self.thinking_log.append(
                        f"  ScreenPilot 工具 [{tool.name}] 触发 GOV HITL (approval_id={sp_approval})"
                    )
                    raise HITLPendingError(sp_approval, tool.name)
                if result.get("success"):
                    finalized = await self._finalize_tool_success(tool, args, result)
                    if tool_name.startswith(("cu_", "ui_")):
                        self._track_screenpilot_session(finalized.get("result", ""))
                    self._memory_record_tool(tool.name, args, finalized)
                    return finalized

                last_error = result.get("error") or result.get("result") or "工具执行失败"
                self.thinking_log.append(
                    f"  工具 [{tool.name}] 第 {attempt + 1} 次返回失败: {str(last_error)[:200]}"
                )

                fallback = await self._try_nl2sql_fallback(tool, args)
                if fallback and fallback.get("success"):
                    self.thinking_log.append("  已通过 nl2sql_query 降级查询成功")
                    self._memory_record_tool(tool.name, args, fallback)
                    return fallback
                if fallback and not fallback.get("success"):
                    self.thinking_log.append(
                        f"  nl2sql_query 降级也失败: {str(fallback.get('error', ''))[:200]}"
                    )

                if attempt < self.tool_retry_count:
                    if self.tool_retry_backoff == "exponential":
                        backoff = (2 ** attempt) * 1.0
                        self.thinking_log.append(f"  指数退避 {backoff}s 后重试...")
                        await asyncio.sleep(backoff)
                    continue
                fail_result = {"success": False, "error": last_error}
                self._memory_record_tool(tool.name, args, fail_result)
                return fail_result
            except Exception as e:
                last_error = str(e)
                self.thinking_log.append(f"  工具 [{tool.name}] 第 {attempt + 1} 次执行异常: {last_error[:200]}")
                fallback = await self._try_nl2sql_fallback(tool, args)
                if fallback and fallback.get("success"):
                    self._memory_record_tool(tool.name, args, fallback)
                    return fallback
                if attempt < self.tool_retry_count:
                    if self.tool_retry_backoff == "exponential":
                        backoff = (2 ** attempt) * 1.0
                        self.thinking_log.append(f"  指数退避 {backoff}s 后重试...")
                        await asyncio.sleep(backoff)
                    continue

        fail_result = {"success": False, "error": last_error or "工具执行失败"}
        self._memory_record_tool(tool.name, args, fail_result)
        return fail_result

    def _memory_record_tool(self, tool_name: str, args: Dict[str, Any], result: Dict[str, Any]):
        if not self.memory_enabled:
            return
        try:
            from services.memory.recorder import MemoryRecorder
            MemoryRecorder(self.db).record_tool_completed(
                agent_id=self.agent.agent_id,
                session_id=self.session.session_id,
                user_id=self.session.caller_id or "",
                tool_name=tool_name,
                success=bool(result.get("success")),
                args=args,
                result_preview=str(result.get("result", ""))[:500],
                error=str(result.get("error", "") or ""),
            )
        except Exception as e:
            print(f"[AgentLoop] 记忆记录工具调用失败: {e}")

    def _memory_record_turn(self, assistant_content: str = ""):
        if not self.memory_enabled:
            return
        try:
            from services.memory.recorder import MemoryRecorder
            MemoryRecorder(self.db).record_message_turn(
                agent_id=self.agent.agent_id,
                session_id=self.session.session_id,
                user_id=self.session.caller_id or "",
                user_message=self.user_message,
                assistant_message=assistant_content or "",
            )
        except Exception as e:
            print(f"[AgentLoop] 记忆记录消息轮次失败: {e}")

    def _memory_record_exception(self, error: str):
        if not self.memory_enabled:
            return
        try:
            from services.memory.recorder import MemoryRecorder
            MemoryRecorder(self.db).record_exception(
                agent_id=self.agent.agent_id,
                session_id=self.session.session_id,
                user_id=self.session.caller_id or "",
                error=error,
            )
        except Exception as e:
            print(f"[AgentLoop] 记忆记录异常失败: {e}")

    def _create_hitl_approval(self, tool_name: str, tool_args: dict, pending_kind: str = "tool_call"):
        """SGL-CFG-06: 创建 HITL 审批工单并挂起 session"""
        from models import HITLApproval, SessionStatus
        approval = HITLApproval(
            approval_id=gen_uuid(),
            session_id=self.session.session_id,
            agent_id=self.agent.agent_id,
            tool_name=tool_name,
            tool_args=tool_args,
            status="PENDING",
        )
        self.db.add(approval)
        # 挂起 session，记录上下文便于审批后恢复
        self.session.status = SessionStatus.HITL_WAIT
        self.session.pending_context = {
            "kind": pending_kind,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "approval_id": approval.approval_id,
            "user_message": self.original_user_message,
        }
        self.session.last_active_at = now_utc()
        self.db.commit()
        self.db.refresh(approval)
        return approval

    async def _run_direct(self) -> Dict[str, Any]:
        self.thinking_log.append("[Direct] 开始分析用户请求...")
        messages = self._build_initial_messages()
        messages = self._truncate_context(messages)

        completion = await self._call_llm(messages)

        choices = completion.get("choices", [])
        if not choices:
            raise ValueError("模型返回空响应")

        assistant_message = choices[0].get("message", {})
        assistant_content = assistant_message.get("content", "")
        reasoning_content = completion.get("reasoning_content", "")
        response_truncated = self._get_finish_reason(completion) == "length"

        history = self._build_history_with_user([
            {"role": "assistant", "content": assistant_content},
        ])
        self._persist_session(history)

        self._extract_and_save_files_from_content(assistant_content, response_truncated=response_truncated)

        return self._build_result(assistant_content, reasoning_content, "direct")

    @staticmethod
    def _build_tool_defs(available_tools: list) -> list:
        from services.tool_service import tool_execution_service

        defs = []
        for t in available_tools:
            if isinstance(t, BuiltinTool):
                defs.append(build_builtin_openai_tool_def(t))
            else:
                defs.append(tool_execution_service.build_openai_tool_def(t))
        return defs

    def _abort_if_requested(self) -> Optional[Dict[str, Any]]:
        from services.session_abort import is_aborted

        sid = getattr(self.session, "session_id", "") or ""
        if not is_aborted(sid):
            return None
        self.thinking_log.append("[中止] 用户取消任务")
        content = "任务已由用户中止。"
        history = self._build_history_with_user([
            {"role": "assistant", "content": content},
        ])
        self._persist_session(history)
        result = self._build_result(content, "\n".join(self.thinking_log), getattr(self, "_abort_mode", "react"))
        result["aborted"] = True
        result["success"] = True
        result["session_status"] = "ACTIVE"
        return result

    async def _run_react(self) -> Dict[str, Any]:
        self._abort_mode = "react"
        openai_tools = self._build_tool_defs(self.available_tools)

        self.thinking_log.append(f"[ReAct] 开始执行, 可用工具: {len(self.available_tools)}")

        messages = self._build_initial_messages()
        messages = self._truncate_context(messages)

        new_messages = []

        iteration = 0
        planning_done = False
        while iteration < self.max_iterations:
            aborted = self._abort_if_requested()
            if aborted:
                return aborted

            iteration += 1
            self.thinking_log.append(f"[ReAct 迭代 {iteration}/{self.max_iterations}]")

            completion = await self._call_llm(messages, tools=openai_tools)

            aborted = self._abort_if_requested()
            if aborted:
                return aborted

            choices = completion.get("choices", [])
            if not choices:
                self.thinking_log.append("模型返回空响应")
                break

            choice = choices[0]
            msg = choice.get("message", {})

            if msg.get("content"):
                if not planning_done and iteration == 1:
                    self.thinking_log.append(f"[规划] {msg['content'][:300]}")
                    planning_done = True
                else:
                    self.thinking_log.append(f"思考: {msg['content'][:200]}")

            tool_calls = self._parse_tool_calls(msg)

            if tool_calls:
                self.thinking_log.append(f"调用 {len(tool_calls)} 个工具")

                assistant_entry = {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                }
                tc_list = []
                for tc in tool_calls:
                    tc_list.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    })
                assistant_entry["tool_calls"] = tc_list
                messages.append(assistant_entry)
                new_messages.append(assistant_entry)

                for tc in tool_calls:
                    aborted = self._abort_if_requested()
                    if aborted:
                        return aborted

                    func_name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments", "")
                    func_args = self._safe_parse_tool_args(raw_args)

                    parse_failed = bool(raw_args) and not func_args


                    tool = next((t for t in self.available_tools if t.name == func_name), None)
                    if tool:
                        if parse_failed:
                            tool_result_str = (
                                f"工具调用参数解析失败。请确保 arguments 是合法的 JSON 字符串，"
                                f"特别注意：1) 字符串中的换行符需用 \\n 转义；"
                                f"2) 字符串中的引号需用 \\\" 转义；"
                                f"3) 大文件内容建议通过代码块输出而非工具参数传递。"
                            )
                            self.thinking_log.append(f"  工具 [{func_name}] 参数解析失败: {raw_args[:200]}")
                        else:
                            # SGL-IMP-03: 死循环检测
                            if self._check_dead_loop(func_name, func_args):
                                tool_result_str = f"检测到死循环：连续 {self.max_repeat_threshold} 次以相同参数调用 {func_name}，已强制中断。请尝试不同的方法。"
                            else:
                                exec_result = await self._execute_tool_with_retry(tool, func_args)
                                if exec_result.get("success"):
                                    tool_result_str = exec_result.get("result", "")
                                else:
                                    tool_result_str = f"工具执行错误: {exec_result.get('error', '')}"
                                self._extract_files_from_result(tool_result_str)
                                tool_result_str = self._compact_tool_result_for_llm(func_name, tool_result_str)
                            self.thinking_log.append(f"  工具 [{func_name}] 结果: {tool_result_str[:200]}")
                    else:
                        tool_result_str = f"工具 {func_name} 未找到，可用工具: {[t.name for t in self.available_tools]}"
                        self.thinking_log.append(f"  {tool_result_str}")

                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result_str,
                    }
                    messages.append(tool_msg)
                    new_messages.append(tool_msg)

                messages = self._truncate_context(messages)
                continue

            assistant_content = msg.get("content", "")
            reasoning_content = completion.get("reasoning_content", "")
            response_truncated = self._get_finish_reason(completion) == "length"

            new_messages.append({"role": "assistant", "content": assistant_content})

            history = self._build_history_with_user(new_messages)
            self._persist_session(history)

            self._extract_and_save_files_from_content(assistant_content, response_truncated=response_truncated)

            return self._build_result(assistant_content, reasoning_content, "react")

        history = self._build_history_with_user(new_messages)
        if not new_messages:
            history.append({"role": "assistant", "content": "已达到最大迭代次数，任务未完成。"})
        self._persist_session(history)

        return self._build_result(
            "任务执行超时，已达到最大迭代次数。请尝试简化问题或增加超时时间。",
            "\n".join(self.thinking_log),
            "react",
        )

    async def _run_plan_and_execute(self) -> Dict[str, Any]:
        self._abort_mode = "plan_and_execute"
        self.thinking_log.append("[Plan-and-Execute] 开始规划阶段")

        aborted = self._abort_if_requested()
        if aborted:
            return aborted

        messages = self._build_initial_messages()
        messages = self._truncate_context(messages)

        plan_prompt = (
            "请先制定一个执行计划。列出需要执行的步骤，每步一行，格式为：\n"
            "- 步骤N: 描述 [可选: 工具名称]\n"
            "然后给出最终答案。"
        )
        plan_messages = list(messages)
        plan_messages.append({"role": "user", "content": plan_prompt})

        plan_completion = await self._call_llm(plan_messages)

        aborted = self._abort_if_requested()
        if aborted:
            return aborted

        plan_choices = plan_completion.get("choices", [])
        if not plan_choices:
            plan_content = "无法生成计划"
        else:
            plan_content = plan_choices[0].get("message", {}).get("content", "")

        self.thinking_log.append(f"计划内容:\n{plan_content[:500]}")

        steps = re.findall(
            r"-\s*步骤?\d+[：:]\s*(.+?)(?=\n-\s*步骤?\d+[：:]|\n\n|$)",
            plan_content + "\n", re.DOTALL,
        )
        if not steps:
            steps = [
                line.strip("- ").strip()
                for line in plan_content.split("\n")
                if line.strip().startswith("-") and len(line.strip()) > 2
            ]

        if not steps:
            steps = [plan_content]

        self.thinking_log.append(f"[Plan-and-Execute] 开始执行阶段，共 {len(steps)} 个步骤")

        openai_tools = (
            self._build_tool_defs(self.available_tools)
            if self.available_tools else None
        )

        execute_messages = list(messages)
        step_results = []

        for i, step in enumerate(steps):
            aborted = self._abort_if_requested()
            if aborted:
                return aborted

            step_text = step.strip()[:500]
            self.thinking_log.append(f"  执行步骤 {i + 1}/{len(steps)}: {step_text[:100]}")

            execute_messages.append({
                "role": "user",
                "content": f"请执行计划中的第 {i + 1} 步: {step_text}",
            })
            execute_messages = self._truncate_context(execute_messages)

            step_completion = await self._call_llm(
                execute_messages,
                tools=openai_tools,
                max_tokens=2048,
            )

            aborted = self._abort_if_requested()
            if aborted:
                return aborted

            step_choices = step_completion.get("choices", [])
            if step_choices:
                step_msg = step_choices[0].get("message", {})
                step_content = step_msg.get("content", "")

                tool_calls = self._parse_tool_calls(step_msg)
                if tool_calls:
                    for tc in tool_calls:
                        aborted = self._abort_if_requested()
                        if aborted:
                            return aborted

                        func_name = tc["function"]["name"]
                        raw_args = tc["function"].get("arguments", "")
                        func_args = self._safe_parse_tool_args(raw_args)

                        parse_failed = bool(raw_args) and not func_args

                        tool = next((t for t in self.available_tools if t.name == func_name), None)
                        if tool:
                            if parse_failed:
                                tool_result_str = (
                                    f"工具调用参数解析失败。请确保 arguments 是合法的 JSON 字符串，"
                                    f"特别注意：1) 字符串中的换行符需用 \\n 转义；"
                                    f"2) 字符串中的引号需用 \\\" 转义；"
                                    f"3) 大文件内容建议通过代码块输出而非工具参数传递。"
                                )
                                self.thinking_log.append(f"    工具 [{func_name}] 参数解析失败: {raw_args[:200]}")
                            else:
                                # SGL-IMP-03: 死循环检测
                                if self._check_dead_loop(func_name, func_args):
                                    tool_result_str = f"检测到死循环：连续 {self.max_repeat_threshold} 次以相同参数调用 {func_name}，已强制中断。"
                                else:
                                    exec_result = await self._execute_tool_with_retry(tool, func_args)
                                    if exec_result.get("success"):
                                        tool_result_str = exec_result.get("result", "")
                                    else:
                                        tool_result_str = f"工具执行错误: {exec_result.get('error', '')}"
                                    self._extract_files_from_result(tool_result_str)
                                    tool_result_str = self._compact_tool_result_for_llm(func_name, tool_result_str)
                                self.thinking_log.append(f"    工具 [{func_name}]: {tool_result_str[:200]}")
                            step_content += f"\n\n工具结果: {tool_result_str}"
                            blocker = self._parse_screenpilot_blocker(tool_result_str)
                            if blocker and blocker.get("kind") == "risk_blocked":
                                self.thinking_log.append(
                                    f"[风控中止] 步骤 {i + 1}/{len(steps)} 检测到 "
                                    f"error_code={blocker.get('error_code')}，停止后续步骤"
                                )
                                step_results.append(step_content)
                                final_content = (
                                    "当前操作被页面安全/网络限制拦截，流程已中止。\n\n"
                                    f"- error_code: `{blocker.get('error_code')}`\n"
                                    f"- 当前 URL: `{blocker.get('url') or '未知'}`\n"
                                    f"- 说明: {blocker.get('warning') or '风险页'}\n\n"
                                    f"**恢复建议:** {blocker.get('recovery_hint') or '请检查系统 risk_rules / entry_url 与网络环境后重试。'}"
                                )
                                history = self._build_history_with_user([
                                    {"role": "assistant", "content": final_content},
                                ])
                                self._persist_session(history)
                                return self._build_result(
                                    final_content, "\n".join(self.thinking_log), "plan_and_execute"
                                )
                            if blocker and blocker.get("kind") == "no_effect":
                                self.thinking_log.append(
                                    f"[无效果] 步骤 {i + 1}/{len(steps)}: {blocker.get('warning')}"
                                )
                                step_content += (
                                    f"\n\n注意: {blocker.get('warning')}；"
                                    f"{blocker.get('recovery_hint')}"
                                )

                step_results.append(step_content)
                execute_messages.append({"role": "assistant", "content": step_content})

        self.thinking_log.append("[Plan-and-Execute] 汇总结果")

        execute_messages.append({
            "role": "user",
            "content": "请根据以上各步骤的执行结果，给出最终的综合回答。如果需要生成文件（如 .drawio、.xml、.json 等），请在回答中输出完整的文件内容，并用代码块标记。",
        })

        final_completion = await self._call_llm(execute_messages, max_tokens=8192)

        final_choices = final_completion.get("choices", [])
        if not final_choices:
            final_content = "\n\n".join(step_results)
            response_truncated = False
        else:
            final_content = final_choices[0].get("message", {}).get("content", "")
            response_truncated = self._get_finish_reason(final_completion) == "length"

        reasoning_content = final_completion.get("reasoning_content", "")

        self._extract_and_save_files_from_content(final_content, response_truncated=response_truncated)

        history = self._build_history_with_user([
            {"role": "assistant", "content": final_content},
        ])
        self._persist_session(history)

        return self._build_result(final_content, reasoning_content, "plan_and_execute")

    def _persist_session(self, history: List[Dict[str, Any]]):
        self.session.messages = history
        self.session.token_used = (self.session.token_used or 0) + self.total_tokens_used
        self.session.last_active_at = now_utc()
        self.db.commit()

    def _build_result(self, content: str, thinking: str, mode: str) -> Dict[str, Any]:
        content = self._replace_file_references(content)
        result = {
            "content": content,
            "thinking": "\n".join(self.thinking_log) + "\n" + (thinking or ""),
            "tokens_used": self.total_tokens_used,
            "total_tokens": self.session.token_used,
            "active_skill": self.active_skill_name,
            "execution_mode": mode,
        }
        if self.generated_files:
            result["files"] = self.generated_files
            if any(f.get("truncated") for f in self.generated_files):
                result["files_truncated"] = True

        # 将 activeSkill / executionMode / files 持久化到 session.messages 的最后一条 assistant 消息中，
        # 确保重新打开历史会话时 Skill 标志、执行模式标签和输出文件卡片都能正常显示
        from sqlalchemy.orm.attributes import flag_modified
        messages = self.session.messages or []
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                if self.active_skill_name:
                    msg["activeSkill"] = self.active_skill_name
                msg["executionMode"] = mode
                if self.generated_files:
                    msg["files"] = self.generated_files
                    if any(f.get("truncated") for f in self.generated_files):
                        msg["filesTruncated"] = True
                break
        self.session.messages = messages
        flag_modified(self.session, "messages")
        self.db.commit()

        # 自我记录：消息轮次
        self._memory_record_turn(assistant_content=content or "")

        # 成功驭屏会话结束后：将未编译轨迹自动写入 UI 技能库
        if mode in ("react", "plan_and_execute"):
            try:
                from services.screenpilot.trajectory import auto_compile_pending_trajectories

                compiled = auto_compile_pending_trajectories(
                    self.db,
                    vela_session_id=self.session.session_id,
                    name_hint=self.original_user_message or "",
                    screen_session_ids=list(getattr(self, "_screenpilot_session_ids", set()) or []),
                )
                if compiled:
                    names = ", ".join(c.get("name", "") for c in compiled)
                    self.thinking_log.append(f"[UI技能] 自动编译 {len(compiled)} 条: {names}")
                    result["thinking"] = "\n".join(self.thinking_log) + "\n" + (thinking or "")
                    result["compiled_ui_skills"] = [
                        {"skill_id": c.get("skill_id"), "name": c.get("name"), "step_count": c.get("step_count")}
                        for c in compiled
                    ]
            except Exception as _e:

        return result

    def _replace_file_references(self, content: str) -> str:
        if not self.generated_files or not content:
            return content

        file_by_name = {}
        for f in self.generated_files:
            name_lower = f["name"].lower()
            file_by_name[name_lower] = f
            name_no_ext = os.path.splitext(name_lower)[0]
            file_by_name[name_no_ext] = f

        def replace_ref(match):
            desc = match.group(1)
            ref_path = match.group(2)

            ref_lower = ref_path.lower().strip()
            ref_basename = os.path.basename(ref_lower)
            ref_no_ext = os.path.splitext(ref_basename)[0]

            matched_file = None
            if ref_basename in file_by_name:
                matched_file = file_by_name[ref_basename]
            elif ref_no_ext in file_by_name:
                matched_file = file_by_name[ref_no_ext]
            elif ref_lower in file_by_name:
                matched_file = file_by_name[ref_lower]

            if not matched_file and self.generated_files:
                for f in self.generated_files:
                    f_ext = os.path.splitext(f["name"].lower())[1]
                    ref_ext = os.path.splitext(ref_basename)[1]
                    if f_ext and ref_ext and f_ext in ref_ext:
                        matched_file = f
                        break

            if not matched_file and self.generated_files:
                matched_file = self.generated_files[0]

            if matched_file:
                return f"[📥 下载 {desc}]({matched_file['url']}) ({matched_file['size_display']})"
            return match.group(0)

        content = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            replace_ref,
            content,
        )
        return content

    def _register_file(self, file_path: str, truncated: bool = False) -> Optional[Dict[str, str]]:
        if not file_path or not os.path.isfile(file_path):
            return None

        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1]

        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
        dest_name = f"{file_hash}{ext}"
        dest_path = os.path.join(self.output_dir, dest_name)

        if not os.path.exists(dest_path):
            shutil.copy2(file_path, dest_path)

        file_size = os.path.getsize(dest_path)
        file_info = {
            "name": filename,
            "url": f"/api/v1/files/{self.session.session_id}/{dest_name}",
            "size": file_size,
            "size_display": self._format_size(file_size),
            "truncated": truncated,
        }

        for existing in self.generated_files:
            if existing["name"] == filename:
                if truncated:
                    existing["truncated"] = True
                return existing

        self.generated_files.append(file_info)
        trunc_note = " [可能不完整]" if truncated else ""
        self.thinking_log.append(f"[文件] 生成文件: {filename} ({file_info['size_display']}){trunc_note}")
        return file_info

    @staticmethod
    def _parse_code_blocks(content: str) -> List[tuple]:
        """解析 markdown 代码块，返回 (lang, code, truncated) 列表。"""
        results: List[tuple] = []
        pos = 0
        for match in re.finditer(r'```(\w*)\s*\n(.*?)```', content, re.DOTALL):
            results.append((match.group(1), match.group(2), False))
            pos = match.end()

        remainder = content[pos:]
        if '```' in remainder:
            unclosed = re.search(r'```(\w*)\s*\n(.*)', remainder, re.DOTALL)
            if unclosed and unclosed.group(2).strip():
                results.append((unclosed.group(1), unclosed.group(2), True))
        elif not results and '```' in content:
            unclosed = re.search(r'```(\w*)\s*\n(.*)', content, re.DOTALL)
            if unclosed and unclosed.group(2).strip():
                results.append((unclosed.group(1), unclosed.group(2), True))
        return results

    @staticmethod
    def _get_finish_reason(completion: Dict[str, Any]) -> Optional[str]:
        choices = completion.get("choices", [])
        if choices:
            return choices[0].get("finish_reason")
        return None

    def _extract_files_from_result(self, result_str: str) -> None:
        try:
            data = json.loads(result_str)
            if isinstance(data, dict):
                for key in ("file_path", "output_file", "path", "filename"):
                    if key in data and isinstance(data[key], str):
                        self._register_file(data[key])
                for key in ("files", "generated_files", "outputs"):
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            if isinstance(item, str):
                                self._register_file(item)
                            elif isinstance(item, dict):
                                p = item.get("path") or item.get("file_path") or item.get("filename")
                                if p:
                                    self._register_file(p)
        except (json.JSONDecodeError, TypeError):
            pass

        for pattern in [
            r'(?:文件路径|文件|path|file)[：:]\s*([^\s,，。\n]+)',
            r'(?:保存在|已保存到|写入|生成于|输出到)[：:]?\s*([^\s,，。\n]+)',
        ]:
            for match in re.finditer(pattern, result_str, re.IGNORECASE):
                self._register_file(match.group(1))

    def _extract_and_save_files_from_content(self, content: str, response_truncated: bool = False) -> None:
        if not content:
            print("[DEBUG _extract_files] content is empty, returning")
            return

        ext_map = {
            "xml": ".drawio",
            "drawio": ".drawio",
            "html": ".html",
            "json": ".json",
            "python": ".py",
            "javascript": ".js",
            "typescript": ".ts",
            "yaml": ".yaml",
            "yml": ".yml",
            "csv": ".csv",
            "sql": ".sql",
            "markdown": ".md",
            "text": ".txt",
        }

        code_blocks = self._parse_code_blocks(content)

        for idx, (lang, code, block_truncated) in enumerate(code_blocks):
            code = code.strip()
            if not code:
                continue

            is_truncated = block_truncated or response_truncated

            ext = ext_map.get(lang.lower() if lang else "", "")

            if not ext:
                if code.startswith("<mxGraphModel") or code.startswith("<mxfile"):
                    ext = ".drawio"
                elif code.startswith("<?xml") or code.startswith("<mx"):
                    ext = ".drawio"
                elif code.strip().startswith("{") or code.strip().startswith("["):
                    ext = ".json"
                elif code.strip().startswith("<"):
                    ext = ".html"

            if not ext:
                continue

            if idx == 0:
                filename = f"output{ext}"
            else:
                filename = f"output_{idx}{ext}"

            file_path = os.path.join(self.output_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)

            self._register_file(file_path, truncated=is_truncated)

        if not code_blocks:
            raw_xml_patterns = [
                (r'(<mxfile[\s\S]*?</mxfile>)', ".drawio"),
                (r'(<mxGraphModel[\s\S]*?</mxGraphModel>)', ".drawio"),
            ]
            for pattern, ext in raw_xml_patterns:
                for match in re.finditer(pattern, content):
                    xml_content = match.group(1).strip()
                    if len(xml_content) > 200:
                        filename = f"output{ext}"
                        file_path = os.path.join(self.output_dir, filename)
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(xml_content)
                        self._register_file(file_path)
                        return

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"


def _ensure_files_for_session(session, db) -> None:
    """加载会话时，为缺少 files 的 assistant 消息自动提取代码块并生成文件。

    这主要用于修复在持久化 files 功能之前创建的旧会话。
    """
    import shutil
    from sqlalchemy.orm.attributes import flag_modified

    messages = session.messages or []
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "outputs", session.session_id
    )
    os.makedirs(output_dir, exist_ok=True)

    ext_map = {
        "xml": ".drawio", "drawio": ".drawio", "html": ".html",
        "json": ".json", "python": ".py", "javascript": ".js",
        "typescript": ".ts", "yaml": ".yaml", "yml": ".yml",
        "csv": ".csv", "sql": ".sql", "markdown": ".md", "text": ".txt",
    }

    modified = False
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        if msg.get("files"):
            continue

        content = msg.get("content", "")
        if not content:
            continue

        code_blocks = AgentLoop._parse_code_blocks(content)
        if not code_blocks:
            continue

        file_infos = []
        for idx, (lang, code, block_truncated) in enumerate(code_blocks):
            code = code.strip()
            if not code:
                continue

            ext = ext_map.get(lang.lower() if lang else "", "")
            if not ext:
                if code.startswith("<mxGraphModel") or code.startswith("<mxfile"):
                    ext = ".drawio"
                elif code.startswith("<?xml") or code.startswith("<mx"):
                    ext = ".drawio"
                elif code.strip().startswith("{") or code.strip().startswith("["):
                    ext = ".json"
                elif code.strip().startswith("<"):
                    ext = ".html"
            if not ext:
                continue

            filename = f"output{ext}" if idx == 0 else f"output_{idx}{ext}"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)

            file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
            dest_name = f"{file_hash}{ext}"
            dest_path = os.path.join(output_dir, dest_name)
            if not os.path.exists(dest_path):
                shutil.copy2(file_path, dest_path)

            file_size = os.path.getsize(dest_path)
            file_infos.append({
                "name": filename,
                "url": f"/api/v1/files/{session.session_id}/{dest_name}",
                "size": file_size,
                "size_display": AgentLoop._format_size(file_size),
                "truncated": block_truncated,
            })

        if file_infos:
            msg["files"] = file_infos
            if any(f.get("truncated") for f in file_infos):
                msg["filesTruncated"] = True
            modified = True

    if modified:
        session.messages = messages
        flag_modified(session, "messages")
        db.commit()


def _compute_skill_relevance(message: str, skill) -> float:
    query_words = set(message.lower().split())
    if not query_words:
        return 0.0

    skill_text = f"{skill.name} {skill.description or ''}"
    for tool in (skill.tools or []):
        if isinstance(tool, dict):
            skill_text += f" {tool.get('name', '')} {tool.get('description', '')}"

    skill_words = set(skill_text.lower().split())
    if not skill_words:
        return 0.0

    overlap = query_words & skill_words
    return len(overlap) / min(len(query_words), len(skill_words) or 1)


def _looks_like_otp_message(message: str) -> bool:
    """User pasted a short numeric OTP into chat."""
    import re
    return bool(re.fullmatch(r"\d{4,8}", (message or "").strip()))


def _session_has_screenpilot_context(session) -> bool:
    """True if this chat recently used ScreenPilot / is mid login-OTP flow."""
    pending = session.pending_context or {}
    if pending.get("kind") in ("screenpilot", "otp_wait", "tool_call"):
        return True
    blob_parts = []
    for msg in (session.messages or [])[-16:]:
        if not isinstance(msg, dict):
            continue
        blob_parts.append(str(msg.get("content") or ""))
        meta = msg.get("meta") or {}
        if isinstance(meta, dict):
            blob_parts.append(str(meta.get("pending_tool_name") or ""))
            pp = meta.get("preview_payload") or {}
            if isinstance(pp, dict):
                blob_parts.append(str(pp.get("flow_kind") or ""))
    blob = "\n".join(blob_parts).lower()
    markers = (
        "cu_navigate", "cu_act", "cu_observe", "cu_wait_for_otp", "cu_login_otp",
        "screen_session", "otp_wait", "screenpilot", "验证码", "login_macro",
    )
    return any(m.lower() in blob for m in markers)


def _analyze_execution_mode(message: str, has_tools: bool, has_kb: bool, has_skills: bool) -> str:
    multi_step_keywords = [
        "先", "然后", "接着", "最后", "步骤", "第一步", "第二步",
        "首先", "其次", "再", "之后", "流程", "依次", "先后",
        "first", "then", "next", "finally", "step", "plan",
    ]
    analysis_keywords = [
        "分析", "对比", "比较", "评估", "总结", "归纳", "概括",
        "analyze", "compare", "evaluate", "summarize", "review",
    ]
    action_keywords = [
        "查询", "搜索", "获取", "调用", "执行", "计算", "生成",
        "search", "get", "fetch", "call", "execute", "calculate",
    ]

    msg_lower = message.lower()

    multi_step_count = sum(1 for kw in multi_step_keywords if kw in msg_lower)
    analysis_count = sum(1 for kw in analysis_keywords if kw in msg_lower)
    action_count = sum(1 for kw in action_keywords if kw in msg_lower)

    if multi_step_count >= 2 and has_tools:
        return "plan_and_execute"
    if multi_step_count >= 1 and analysis_count >= 1 and has_tools:
        return "plan_and_execute"

    if has_skills:
        return "direct"

    if has_kb and (action_count >= 1 or has_tools):
        return "react"

    if has_tools and action_count >= 1:
        return "react"

    return "direct"


agent_service = AgentService()