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
    ) -> Dict[str, Any]:
        """WF: 统一处理工作流 chat 响应与 session 写入"""
        messages = session.messages or []
        if message and message.strip():
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
    async def chat_with_agent(
        db: Session,
        agent_id: str,
        session_id: str,
        message: str,
        skill_pack_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        execution_mode: Optional[str] = "auto",
        skip_history: bool = False,
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
                db, session, message, result
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
                db, session, message, result
            )

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

        loop = AgentLoop(
            db=db,
            agent=agent,
            session=session,
            provider=provider,
            model_svc=model_svc,
            available_tools=available_tools,
            timeout_seconds=timeout_seconds,
            user_message=message,
            active_skill_name=active_skill_name,
            knowledge_context=knowledge_context,
            skill_context=skill_context,
            skip_history=skip_history,
        )

        try:
            result = await loop.run(mode)
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
            except Exception:
                pass
            return {
                "content": f"⏸️ 工具 [{he.tool_name}] 需要人工审批后才能继续执行。\n审批工单 ID: `{he.approval_id}`\n\n请在审批中心处理后继续对话。",
                "thinking": "\n".join(loop.thinking_log) if loop else "",
                "tokens_used": 0,
                "total_tokens": session.token_used or 0,
                "execution_mode": "hitl_pending",
                "files": [],
                "pending_approval_id": he.approval_id,
                "pending_tool_name": he.tool_name,
                "preview_payload": preview_payload,
                "session_status": "HITL_WAIT",
            }
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
    ):
        self.db = db
        self.agent = agent
        self.session = session
        self.provider = provider
        self.model_svc = model_svc
        self.available_tools = available_tools
        self.timeout_seconds = timeout_seconds
        self.user_message = user_message
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

        messages.append({"role": "user", "content": self.user_message})
        return messages

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
        if not name.startswith("ui_") or not result.get("success"):
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

    async def _execute_tool_with_retry(self, tool, args: Dict[str, Any]) -> Dict[str, Any]:
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
            "user_message": self.user_message,
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

        history = self.session.messages or []
        history.append({"role": "user", "content": self.user_message})
        history.append({"role": "assistant", "content": assistant_content})
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

    async def _run_react(self) -> Dict[str, Any]:
        openai_tools = self._build_tool_defs(self.available_tools)

        self.thinking_log.append(f"[ReAct] 开始执行, 可用工具: {len(self.available_tools)}")

        messages = self._build_initial_messages()
        messages = self._truncate_context(messages)

        new_messages = []

        iteration = 0
        planning_done = False
        while iteration < self.max_iterations:
            iteration += 1
            self.thinking_log.append(f"[ReAct 迭代 {iteration}/{self.max_iterations}]")

            completion = await self._call_llm(messages, tools=openai_tools)

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

            history = (self.session.messages or []) + [{"role": "user", "content": self.user_message}] + new_messages
            self._persist_session(history)

            self._extract_and_save_files_from_content(assistant_content, response_truncated=response_truncated)

            return self._build_result(assistant_content, reasoning_content, "react")

        history = (self.session.messages or []) + [{"role": "user", "content": self.user_message}] + new_messages
        if not new_messages:
            history.append({"role": "assistant", "content": "已达到最大迭代次数，任务未完成。"})
        self._persist_session(history)

        return self._build_result(
            "任务执行超时，已达到最大迭代次数。请尝试简化问题或增加超时时间。",
            "\n".join(self.thinking_log),
            "react",
        )

    async def _run_plan_and_execute(self) -> Dict[str, Any]:
        self.thinking_log.append("[Plan-and-Execute] 开始规划阶段")

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

            step_choices = step_completion.get("choices", [])
            if step_choices:
                step_msg = step_choices[0].get("message", {})
                step_content = step_msg.get("content", "")

                tool_calls = self._parse_tool_calls(step_msg)
                if tool_calls:
                    for tc in tool_calls:
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
                                self.thinking_log.append(f"    工具 [{func_name}]: {tool_result_str[:200]}")
                            step_content += f"\n\n工具结果: {tool_result_str}"

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

        history = (self.session.messages or []) + [
            {"role": "user", "content": self.user_message},
            {"role": "assistant", "content": final_content},
        ]
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