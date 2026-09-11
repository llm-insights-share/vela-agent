"""
MA: 多 Agent 协调调度引擎
实现 Coordinator → Specialist 的任务分派、A2A 通信、结果汇总
"""
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import (
    Agent, AgentComposition, AuditLog, SessionStatus, gen_uuid,
)

logger = logging.getLogger(__name__)


class TokenBudgetExceededError(Exception):
    """MA-IMP-08: Token 预算熔断"""
    pass


class A2ACallLimitExceededError(Exception):
    """MA-IMP-06: A2A 调用次数超限"""
    pass


class CoordinatorEngine:
    """多 Agent 协调调度引擎

    负责：
    - MA-IMP-01: 解析用户任务，动态决定调用哪个/哪些子 Agent
    - MA-IMP-02: 分派轮次计数器
    - MA-IMP-03: 子 Agent 执行结果结构化回传
    - MA-IMP-04: Coordinator 汇总逻辑
    - MA-IMP-05~07: A2A 通信层
    - MA-IMP-08: Token 预算实时累加与熔断
    - MA-IMP-09: 交付前 HITL Gate
    - MA-IMP-10: 子 Agent 故障隔离
    - MA-IMP-11: 调度轨迹记录
    """

    def __init__(self, db, parent_agent: Agent, session, provider, model_svc):
        self.db = db
        self.parent_agent = parent_agent
        self.session = session
        self.provider = provider
        self.model_svc = model_svc

        # 从 composition_config 读取配置
        config = parent_agent.composition_config or {}
        self.dispatch_strategy = config.get("dispatch_strategy", "llm")
        self.max_rounds = config.get("max_dispatch_rounds", 5)
        self.result_integration = config.get("result_integration", "coordinator")
        self.coordinator_model_service_id = config.get("coordinator_model_service_id")
        self.a2a_whitelist = config.get("a2a_direct_whitelist", [])
        # MA-IMP-09: 默认关闭交付前 HITL，仅在 composition_config 中显式开启时生效
        self.hitl_before_delivery = config.get("hitl_before_delivery", False)
        self.token_budget = config.get("total_token_budget", 500000)
        self.max_a2a_calls = config.get("max_a2a_calls", 20)
        # Prevent endless re-dispatch of the same specialist (unused roles like reporter
        # previously blocked the "all agents done" hard-stop and burned the token budget).
        self.max_calls_per_agent = max(1, int(config.get("max_calls_per_agent") or 2))
        self.child_max_iterations = max(1, int(config.get("child_max_iterations") or 6))
        # Soft-stop before the next A2A when remaining budget is too small for another specialist.
        self.min_tokens_for_dispatch = max(0, int(config.get("min_tokens_for_dispatch") or 40000))

        # 运行时状态
        self.dispatch_count = 0
        self.a2a_call_count = 0
        self.total_tokens = 0
        self.trace_id = session.trace_id or str(uuid.uuid4())
        self.audit_trail: List[Dict[str, Any]] = []
        self.thinking_log: List[str] = []
        self._child_sessions: Dict[str, str] = {}  # child_agent_id -> session_id (reuse within run)

    def _attach_execution_story(
        self,
        payload: Dict[str, Any],
        *,
        user_message: str = "",
        hitl: bool = False,
        status: str = "done",
    ) -> Dict[str, Any]:
        """Attach structured multi-agent execution_story to coordinator result."""
        from services.execution_story import ExecutionStoryBuilder

        story_status = "hitl_wait" if hitl else status
        payload["execution_story"] = ExecutionStoryBuilder.from_coordinator(
            payload.get("audit_trail") or self.audit_trail,
            payload.get("thinking_log") or self.thinking_log,
            user_message=user_message,
            status=story_status,
            hitl=hitl,
            metrics={
                "tool_calls": len(self.audit_trail),
                "iterations": self.dispatch_count,
            },
        )
        return payload

    async def run(self, user_message: str) -> Dict[str, Any]:
        """主调度循环"""
        self.thinking_log.append(f"[Coordinator] 开始处理用户任务: {user_message[:200]}")

        # 加载子 Agent 列表
        sub_agents = self._load_sub_agents()
        if not sub_agents:
            # No specialists configured: coordinator answers directly
            final_result = await self._direct_coordinator_reply(user_message)
            self.thinking_log.append("[Coordinator] 未配置子 Agent，由 Coordinator 直接回复")
            return self._attach_execution_story({
                "success": True,
                "result": final_result,
                "pending_approval_id": None,
                "pending_delivery": False,
                "thinking_log": self.thinking_log,
                "audit_trail": self.audit_trail,
                "total_tokens": self.total_tokens,
                "dispatch_count": 0,
                "a2a_call_count": 0,
            }, user_message=user_message)

        self.thinking_log.append(f"[Coordinator] 可用子 Agent: {[s['role_name'] for s in sub_agents]}")

        all_results: List[Dict[str, Any]] = []
        final_result = ""
        stop_for_budget = False

        for round_num in range(1, self.max_rounds + 1):
            self.dispatch_count = round_num
            self.thinking_log.append(f"[Coordinator] 调度轮次 {round_num}/{self.max_rounds}")

            if self._should_soft_stop_for_budget(all_results):
                stop_for_budget = True
                break

            # Soft stop: enough successful specialist work already (do not wait for unused roles)
            success_ids = {r.get("_agent_id", "") for r in all_results if r.get("success")}
            if len(success_ids) >= 2 and round_num > 2:
                self.thinking_log.append(
                    f"[Coordinator] 已有 {len(success_ids)} 个角色成功产出且轮次>{2}，进入汇总"
                )
                break

            # MA-IMP-01: 按 dispatch_strategy（llm / rule）对全部子 Agent 做 plan
            dispatch_plan = await self._dispatch(user_message, sub_agents, all_results)
            dispatch_plan = self._filter_dispatch_by_call_caps(dispatch_plan, all_results)
            if not dispatch_plan:
                self.thinking_log.append("[Coordinator] 无需继续分派，进入汇总阶段")
                break

            # 执行分派的子 Agent
            round_results = []
            for child_agent_id, task in dispatch_plan:
                if self._should_soft_stop_for_budget(all_results):
                    stop_for_budget = True
                    break

                # MA-IMP-06: A2A 调用次数检查
                self._check_a2a_limit()

                # MA-IMP-10: 故障隔离
                result = await self._execute_sub_agent_safely(child_agent_id, task)
                round_results.append(result)
                all_results.append(result)


                if self.total_tokens > self.token_budget and any(r.get("success") for r in all_results):
                    self.thinking_log.append(
                        f"[Coordinator] Token 已超预算 {self.total_tokens}/{self.token_budget}，停止继续分派并汇总已有结果"
                    )
                    stop_for_budget = True
                    break

            if stop_for_budget:
                break

            # 判断是否需要继续分派
            if self.result_integration == "concat" and round_num >= 1:
                # 直接拼接模式，一轮即可
                break

        if stop_for_budget:
            self.thinking_log.append("[Coordinator] 因 Token 预算软熔断进入汇总")

        # No successful sub-agent work: answer directly, skip empty delivery HITL
        has_success = any(r.get("success") for r in all_results)
        if not has_success:
            final_result = await self._direct_coordinator_reply(user_message)
            self.thinking_log.append(
                "[Coordinator] 无子 Agent 成功结果，改为 Coordinator 直接回复（跳过交付 HITL）"
            )
            return self._attach_execution_story({
                "success": True,
                "result": final_result,
                "pending_approval_id": None,
                "pending_delivery": False,
                "thinking_log": self.thinking_log,
                "audit_trail": self.audit_trail,
                "total_tokens": self.total_tokens,
                "dispatch_count": self.dispatch_count,
                "a2a_call_count": self.a2a_call_count,
            }, user_message=user_message)

        # MA-IMP-04: 结果汇总
        if self.result_integration == "coordinator":
            final_result = await self._summarize_results(user_message, all_results)
        else:
            final_result = self._concat_success_results(all_results)

        # Empty summary must never ship to HITL (approve would show blank delivery)
        if not (final_result or "").strip():
            final_result = self._concat_success_results(all_results) or "没有可汇总的子 Agent 结果"
            self.thinking_log.append(
                f"[Coordinator] 汇总结果为空，已降级为成功子 Agent 拼接 (len={len(final_result)})"
            )


        # MA-IMP-09: 交付前 HITL Gate - 真正创建审批工单并挂起 session
        pending_approval_id = None
        if self.hitl_before_delivery:
            from models import HITLApproval, SessionStatus
            approval = HITLApproval(
                approval_id=gen_uuid(),
                session_id=self.session.session_id,
                agent_id=self.parent_agent.agent_id,
                tool_name="__delivery__",
                tool_args={"final_result": final_result, "user_message": user_message},
                status="PENDING",
            )
            self.db.add(approval)
            self.session.status = SessionStatus.HITL_WAIT
            self.session.pending_context = {
                "kind": "delivery",
                "approval_id": approval.approval_id,
                "final_result": final_result,
                "user_message": user_message,
            }
            self.session.last_active_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(approval)
            pending_approval_id = approval.approval_id
            self.thinking_log.append(
                f"[Coordinator] 交付前 HITL Gate 已触发，等待人工审批 (approval_id={pending_approval_id})"
            )

        self.thinking_log.append(f"[Coordinator] 任务完成，总 Token: {self.total_tokens}")

        return self._attach_execution_story({
            "success": True,
            "result": final_result if not pending_approval_id else "",
            "pending_approval_id": pending_approval_id,
            "pending_delivery": bool(pending_approval_id),
            "thinking_log": self.thinking_log,
            "audit_trail": self.audit_trail,
            "total_tokens": self.total_tokens,
            "dispatch_count": self.dispatch_count,
            "a2a_call_count": self.a2a_call_count,
        }, user_message=user_message, hitl=bool(pending_approval_id))

    def _load_sub_agents(self) -> List[Dict[str, Any]]:
        """加载子 Agent 配置"""
        compositions = self.db.query(AgentComposition).filter(
            AgentComposition.parent_agent_id == self.parent_agent.agent_id
        ).all()

        sub_agents = []
        for comp in compositions:
            child = self.db.query(Agent).filter(Agent.agent_id == comp.child_agent_id).first()
            if child and child.status.value == "PUBLISHED":
                sub_agents.append({
                    "agent_id": child.agent_id,
                    "name": child.name,
                    "role_name": comp.role_name,
                    "role_description": comp.role_description or "",
                    "task_keywords": comp.task_keywords or [],
                    "child_agent": child,
                })
        return sub_agents

    def _keyword_matched_agents(
        self, user_message: str, sub_agents: List[Dict]
    ) -> List[Dict]:
        """Return specialists whose task_keywords appear in the user message."""
        msg = (user_message or "").lower()
        matched: List[Dict] = []
        for sa in sub_agents:
            kws = sa.get("task_keywords") or []
            if not kws:
                continue
            if any(str(kw).lower() in msg for kw in kws if kw):
                matched.append(sa)
        return matched

    async def _dispatch(
        self, user_message: str, sub_agents: List[Dict], previous_results: List[Dict]
    ) -> List[tuple]:
        """MA-IMP-01: 任务分派 - LLM 自主 plan / 规则关键词匹配"""
        if self.dispatch_strategy == "rule":
            return self._rule_dispatch(user_message, sub_agents)

        return await self._llm_dispatch(user_message, sub_agents, previous_results)

    def _rule_dispatch(
        self, user_message: str, sub_agents: List[Dict]
    ) -> List[tuple]:
        """规则匹配分派：按 task_keywords 命中；无命中则空 plan（后续 Coordinator 自答）"""
        matched = self._keyword_matched_agents(user_message, sub_agents)
        return [(sa["agent_id"], user_message) for sa in matched]

    async def _llm_dispatch(
        self, user_message: str, sub_agents: List[Dict], previous_results: List[Dict]
    ) -> List[tuple]:
        """LLM 根据全部子 Agent 职责做 plan 与编排"""
        # 构建 id -> 元信息映射，用于回退匹配
        self._sub_agent_index = {sa["agent_id"]: sa for sa in sub_agents}

        # 构建分派 Prompt（明确给出真实 agent_id，避免 LLM 编造）
        agent_descriptions = "\n".join([
            f"- agent_id={sa['agent_id']} | 角色名={sa['role_name']} | Agent名称={sa['name']} | 职责={sa['role_description']} | 关键词={sa.get('task_keywords') or []}"
            for sa in sub_agents
        ])

        prev_summary = ""
        if previous_results:
            prev_parts = []
            for i, r in enumerate(previous_results):
                role = r.get('role_name', 'unknown')
                result_text = r.get('result', '')
                success = r.get('success', False)
                prev_parts.append(
                    f"--- 第{i+1}次执行结果 ({role}, success={success}) ---\n{result_text[:500]}"
                )
            prev_summary = "\n\n".join(prev_parts)

        # 如果已有足够成功结果，提示 LLM 应返回 DONE（勿要求未使用的角色也跑一遍）
        all_dispatched_hint = ""
        success_n = sum(1 for r in previous_results if r.get("success"))
        call_counts: Dict[str, int] = {}
        for r in previous_results:
            aid = r.get("_agent_id") or ""
            if aid:
                call_counts[aid] = call_counts.get(aid, 0) + 1
        if success_n >= 2:
            all_dispatched_hint = (
                "\n\n【重要】已有多个子 Agent 成功产出。除非关键证据明显缺失，否则必须返回 DONE。"
                "不要为了调用尚未使用的角色而继续分派；不要重复已经完成的取数/风险识别。"
            )
        elif call_counts:
            capped = [aid for aid, n in call_counts.items() if n >= self.max_calls_per_agent]
            if capped:
                all_dispatched_hint = (
                    f"\n\n【重要】以下 agent_id 已达调用上限({self.max_calls_per_agent})，不要再分派它们："
                    + ", ".join(capped)
                )

        dispatch_prompt = f"""你是一个任务协调者（Coordinator），根据子 Agent 的职责对用户任务做规划与编排。

可用子 Agent（必须严格使用下列 agent_id，不可编造，也不可臆造列表外 Agent）：
{agent_descriptions}

用户任务: {user_message}

{f"之前已完成的子任务结果：\n{prev_summary}" if prev_summary else ""}{all_dispatched_hint}

规则：
- 根据各子 Agent 职责判断是否需要分派、分派给谁、以及具体 task
- 只分派职责与用户任务真正相关的子 Agent；无关角色不要分派
- 若信息已足够、或这是闲聊/自我介绍类问题、或不需要任何子 Agent：直接返回 DONE（将由 Coordinator 自己回答）
- 若需分派：返回 JSON 数组，元素含 agent_id 与 task；可并行分派多个角色
- 不要重复已完成任务，除非确实需要补充

只返回 DONE 或 JSON，不要额外文字。"""

        try:
            response = await self._call_coordinator_llm(dispatch_prompt)
            if "DONE" in response.strip().upper():
                return []

            import json
            # 尝试提取 JSON
            text = response.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            plan = json.loads(text)

            # 容错：LLM 可能返回 dict 而非 list，统一为 list
            if isinstance(plan, dict):
                # 形如 {"agent_id": "...", "task": "..."} 单个对象
                if "agent_id" in plan or "task" in plan:
                    plan = [plan]
                else:
                    # 形如 {"<agent_id>": "<task>"} 映射
                    plan = [{"agent_id": k, "task": v} for k, v in plan.items()]
            if not isinstance(plan, list):
                raise ValueError(f"LLM 返回的 JSON 不是数组: {type(plan).__name__}")

            # 容错：LLM 可能返回 name/role_name 而非真实 UUID，按映射回退
            result = []
            allowed_ids = {sa["agent_id"] for sa in sub_agents}
            for item in plan:
                if not isinstance(item, dict):
                    logger.warning(f"分派项不是 dict: {item!r}，已跳过")
                    continue
                aid = item.get("agent_id", "")
                task = item.get("task", user_message)
                matched_id = self._resolve_agent_id(aid, sub_agents)
                if matched_id and matched_id in allowed_ids:
                    result.append((matched_id, task))
                else:
                    logger.warning(f"LLM 返回的 agent_id '{aid}' 无法匹配任何子 Agent，已跳过")
            return result
        except Exception as e:
            logger.warning(f"LLM 分派失败，降级为关键词规则分派: {e}")
            # Never fan-out to all agents — only keyword matches (may be empty → coordinator answers)
            return self._rule_dispatch(user_message, sub_agents)

    def _resolve_agent_id(self, aid: str, sub_agents: List[Dict]) -> Optional[str]:
        """将 LLM 返回的 agent_id 解析为真实 UUID（容错：可能返回的是 name/role_name）"""
        if not aid:
            return None
        aid_str = str(aid).strip()
        # 1. 直接命中
        if aid_str in self._sub_agent_index:
            return aid_str
        # 2. 按 name 精确匹配
        for sa in sub_agents:
            if sa.get("name", "") == aid_str:
                return sa["agent_id"]
        # 3. 按 role_name 精确匹配
        for sa in sub_agents:
            if sa.get("role_name", "") == aid_str:
                return sa["agent_id"]
        # 4. 按 name/role_name 大小写不敏感包含匹配
        aid_lower = aid_str.lower()
        for sa in sub_agents:
            if aid_lower in (sa.get("name", "").lower() + sa.get("role_name", "").lower()):
                return sa["agent_id"]
        return None

    async def _execute_sub_agent_safely(
        self, child_agent_id: str, task: str
    ) -> Dict[str, Any]:
        """MA-IMP-10: 子 Agent 故障隔离执行"""
        start_time = time.time()
        try:
            result = await self._execute_sub_agent(child_agent_id, task)
            result["_agent_id"] = child_agent_id  # 标记来源，用于去重判断
            duration_ms = int((time.time() - start_time) * 1000)

            # MA-IMP-07: 审计日志
            self._log_audit(
                event_type="a2a_call",
                event_data={
                    "sender": self.parent_agent.agent_id,
                    "receiver": child_agent_id,
                    "task": task[:500],
                    "success": result.get("success", False),
                },
                tokens_used=result.get("tokens_used", 0),
                duration_ms=duration_ms,
            )

            # MA-IMP-11: 调度轨迹
            self.audit_trail.append({
                "round": self.dispatch_count,
                "sender": "Coordinator",
                "receiver": child_agent_id,
                "role_name": result.get("role_name") or child_agent_id,
                "task": task[:200],
                "success": result.get("success", False),
                "duration_ms": duration_ms,
                "tokens": result.get("tokens_used", 0),
                "result_preview": str(result.get("result") or "")[:200],
            })

            self.a2a_call_count += 1
            self.total_tokens += result.get("tokens_used", 0)

            return result

        except Exception as e:
            logger.error(f"子 Agent {child_agent_id} 执行失败: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            self._log_audit(
                event_type="a2a_call_error",
                event_data={
                    "sender": self.parent_agent.agent_id,
                    "receiver": child_agent_id,
                    "error": str(e)[:500],
                },
                tokens_used=0,
                duration_ms=duration_ms,
            )
            return {
                "success": False,
                "role_name": child_agent_id,
                "result": f"子 Agent 执行失败: {str(e)}",
                "tokens_used": 0,
                "error": str(e),
                "_agent_id": child_agent_id,
            }

    async def _execute_sub_agent(
        self, child_agent_id: str, task: str
    ) -> Dict[str, Any]:
        """MA-IMP-03/05: 执行子 Agent，结构化回传"""
        from services.agent_service import agent_service

        child_agent = self.db.query(Agent).filter(Agent.agent_id == child_agent_id).first()
        if not child_agent:
            return {
                "success": False,
                "role_name": "unknown",
                "result": f"子 Agent {child_agent_id} 不存在",
                "tokens_used": 0,
            }

        # Reuse the same child session within one coordinator run so "继续" tasks
        # keep context instead of cold-starting another 12-iteration tool loop.
        from models import Session as AgentSession
        reused = False
        sub_session_id = self._child_sessions.get(child_agent_id)
        if sub_session_id:
            sub_session = self.db.query(AgentSession).filter(
                AgentSession.session_id == sub_session_id
            ).first()
            if sub_session:
                reused = True
            else:
                sub_session_id = None
        if not sub_session_id:
            sub_session = AgentSession(
                session_id=gen_uuid(),
                agent_id=child_agent_id,
                caller_type="AGENT",
                caller_id=self.parent_agent.agent_id,
                status=SessionStatus.ACTIVE,
                token_budget=child_agent.token_budget,
                trace_id=self.trace_id,
            )
            self.db.add(sub_session)
            self.db.commit()
            sub_session_id = sub_session.session_id
            self._child_sessions[child_agent_id] = sub_session_id


        # Cap iterations for specialist loops invoked by coordinator
        original_iters = child_agent.max_iterations
        child_agent.max_iterations = min(int(original_iters or 12), self.child_max_iterations)
        try:
            result = await agent_service.chat_with_agent(
                db=self.db,
                agent_id=child_agent_id,
                session_id=sub_session_id,
                message=task,
                timeout_seconds=120,
            )
        finally:
            child_agent.max_iterations = original_iters

        # AgentLoop._build_result 返回 content/tokens_used/files，
        # 异常路径返回 success/content/error，需兼容两种结构
        out = {
            "success": result.get("success", True) if "error" not in result else False,
            "role_name": child_agent.name,
            "result": result.get("content", ""),
            "tokens_used": result.get("tokens_used", 0),
            "artifacts": result.get("files", []),
            "session_id": sub_session_id,
            "session_reused": reused,
        }
        try:
            from services.session_events import publish_story_patch, publish_thinking_delta
            parent_sid = getattr(self.session, "session_id", None)
            if parent_sid:
                role = child_agent.name or "子 Agent"
                snippet = (out.get("result") or "")[:240]
                publish_thinking_delta(
                    parent_sid,
                    text=f"\n[{role}] 完成子任务\n{snippet}\n",
                    field="content",
                )
                if result.get("execution_story"):
                    publish_story_patch(parent_sid, result["execution_story"])
        except Exception:
            pass
        return out

    def _filter_dispatch_by_call_caps(
        self, plan: List[tuple], previous_results: List[Dict[str, Any]]
    ) -> List[tuple]:
        counts: Dict[str, int] = {}
        for r in previous_results:
            aid = r.get("_agent_id") or ""
            if aid:
                counts[aid] = counts.get(aid, 0) + 1
        filtered = []
        for aid, task in plan or []:
            if counts.get(aid, 0) >= self.max_calls_per_agent:
                self.thinking_log.append(
                    f"[Coordinator] 跳过 {aid[:8]}…：已达每角色上限 {self.max_calls_per_agent}"
                )
                continue
            filtered.append((aid, task))
            counts[aid] = counts.get(aid, 0) + 1
        return filtered

    def _should_soft_stop_for_budget(self, all_results: List[Dict[str, Any]]) -> bool:
        """Prefer summarizing existing work over hard-failing the whole job."""
        remaining = self.token_budget - self.total_tokens
        if self.total_tokens > self.token_budget and any(r.get("success") for r in all_results):
            self.thinking_log.append(
                f"[Coordinator] Token 预算软熔断: {self.total_tokens}/{self.token_budget}"
            )
            return True
        if (
            any(r.get("success") for r in all_results)
            and remaining < self.min_tokens_for_dispatch
        ):
            self.thinking_log.append(
                f"[Coordinator] 剩余 Token 不足再分派 ({remaining}<{self.min_tokens_for_dispatch})，进入汇总"
            )
            return True
        return False


    async def _direct_coordinator_reply(self, user_message: str) -> str:
        """When no sub-agent ran, answer the user directly (avoid empty delivery HITL)."""
        name = getattr(self.parent_agent, "name", None) or "Coordinator"
        prompt = (
            f"你是多 Agent 协调者「{name}」。用户问题不需要分派子 Agent，请直接用中文简洁回答。"
            f"\n\n用户：{user_message}"
        )
        try:
            reply = await self._call_coordinator_llm(prompt)
            if (reply or "").strip():
                return reply.strip()
        except Exception as e:
            logger.warning(f"Coordinator 直接回复失败: {e}")
        return (
            f"我是「{name}」，负责协调审计相关子 Agent 完成采集、风险分析与报告类任务。"
            "当前问题未触发子 Agent 分派；如需审计业务协助，请直接说明具体任务。"
        )

    def _concat_success_results(self, results: List[Dict[str, Any]]) -> str:
        parts = [
            f"【{r.get('role_name', 'unknown')}】{r.get('result', '')}"
            for r in results
            if r.get("success") and (r.get("result") or "").strip()
        ]
        return "\n\n---\n\n".join(parts)

    async def _summarize_results(
        self, user_message: str, results: List[Dict[str, Any]]
    ) -> str:
        """MA-IMP-04: Coordinator 汇总"""
        if not results:
            return "没有可汇总的子 Agent 结果"

        success_results = [r for r in results if r.get("success") and (r.get("result") or "").strip()]
        # 如果只有一个成功结果，直接返回
        if len(success_results) == 1:
            return success_results[0]["result"]
        if not success_results:
            return "没有可汇总的子 Agent 结果"

        # Truncate each result for the summarize prompt to avoid context overflow → empty reply
        max_each = 6000
        results_text = "\n\n".join([
            f"### {r.get('role_name', 'unknown')} 的结果:\n{(r.get('result') or '')[:max_each]}"
            for r in success_results
        ])
        fallback = self._concat_success_results(success_results)

        summary_prompt = f"""你是任务协调者（Coordinator），负责将多个子 Agent 的执行结果整合为统一交付物。

用户原始任务: {user_message}

各子 Agent 执行结果:
{results_text}

请将这些结果整合为一个连贯、完整的回复。保留关键信息，去除冗余，确保逻辑清晰。"""

        try:
            summary = await self._call_coordinator_llm(summary_prompt)
            if (summary or "").strip():
                return summary
            logger.warning("Coordinator 汇总返回空内容，降级为拼接")
            return fallback
        except Exception as e:
            logger.warning(f"汇总失败，降级为拼接: {e}")
            return fallback

    async def _call_coordinator_llm(self, prompt: str) -> str:
        """调用 Coordinator 专用 LLM"""
        from services.model_provider import model_provider_service
        from models import ModelProvider, ModelService

        # 使用 Coordinator 专用模型，或回退到 parent agent 的模型
        model_service_id = self.coordinator_model_service_id or self.parent_agent.model_service_id
        model_service = self.db.query(ModelService).filter(
            ModelService.model_service_id == model_service_id
        ).first()
        if not model_service:
            model_service = self.model_svc

        provider = self.db.query(ModelProvider).filter(
            ModelProvider.provider_id == model_service.provider_id
        ).first()

        messages = [{"role": "user", "content": prompt}]
        parent_sid = getattr(self.session, "session_id", None)

        def _on_delta(kind: str, text: str) -> None:
            from services.session_events import publish_thinking_delta
            if not parent_sid or not text:
                return
            field = "reasoning" if kind == "reasoning" else "content"
            publish_thinking_delta(parent_sid, text=text, field=field)

        # Large multi-agent payloads need more than 60s
        try:
            response = await model_provider_service.chat_completion_stream(
                provider=provider,
                model_name=model_service.model_name,
                messages=messages,
                max_tokens=4096,
                timeout_seconds=120,
                source="coordinator",
                on_delta=_on_delta,
            )
        except Exception as stream_err:
            print(f"[Coordinator] stream failed, fallback: {stream_err}")
            response = await model_provider_service.chat_completion(
                provider=provider,
                model_name=model_service.model_name,
                messages=messages,
                max_tokens=4096,
                timeout_seconds=120,
                source="coordinator",
            )

        tokens = response.get("usage", {}).get("total_tokens", 0)
        self.total_tokens += tokens

        # chat_completion 返回原始 OpenAI 风格响应，content 在 choices[0].message.content
        choices = response.get("choices", []) or []
        if not choices:
            return ""
        msg = choices[0].get("message", {}) or {}
        content = msg.get("content", "") or ""
        if isinstance(content, list):
            content = "".join(
                (p.get("text") if isinstance(p, dict) else str(p)) or ""
                for p in content
            )
        # Some models put the answer only in reasoning/thinking fields
        if not str(content).strip():
            content = (
                msg.get("reasoning_content")
                or response.get("reasoning_content")
                or msg.get("thinking")
                or ""
            )
        return str(content or "")

    def _check_budget(self):
        """MA-IMP-08: Token 预算熔断（无可用结果时才硬失败）"""
        if self.total_tokens > self.token_budget:
            self.thinking_log.append(
                f"[Coordinator] Token 预算熔断: {self.total_tokens}/{self.token_budget}"
            )
            raise TokenBudgetExceededError(
                f"多 Agent 任务超出 Token 预算: {self.total_tokens}/{self.token_budget}"
            )

    def _check_a2a_limit(self):
        """MA-IMP-06: A2A 调用次数限制"""
        if self.a2a_call_count >= self.max_a2a_calls:
            self.thinking_log.append(
                f"[Coordinator] A2A 调用次数超限: {self.a2a_call_count}/{self.max_a2a_calls}"
            )
            raise A2ACallLimitExceededError(
                f"超出最大 A2A 调用次数: {self.a2a_call_count}/{self.max_a2a_calls}"
            )

    def _log_audit(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        tokens_used: int = 0,
        duration_ms: int = 0,
    ):
        """MA-IMP-07: 审计日志"""
        log = AuditLog(
            log_id=gen_uuid(),
            agent_id=self.parent_agent.agent_id,
            session_id=self.session.session_id,
            event_type=event_type,
            event_data=event_data,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            trace_id=self.trace_id,
        )
        self.db.add(log)
        self.db.commit()
