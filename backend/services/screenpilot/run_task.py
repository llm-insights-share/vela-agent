"""RSN 层 POC — ui_run_task Observe-Plan-Act-Verify 循环（无 LangGraph）。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.screenpilot.service import navigate_ui, observe_session, replay_skill, search_skills
from services.screenpilot.skill_store import skill_store

logger = logging.getLogger(__name__)


def _goal_keywords(goal: str) -> List[str]:
    raw = [w.strip() for w in goal.replace("，", " ").replace(",", " ").split() if w.strip()]
    keys: List[str] = []
    for w in raw:
        if len(w) <= 2:
            keys.append(w)
        else:
            keys.extend([w[i : i + 2] for i in range(len(w) - 1)])
    return keys


def _verify_goal(goal: str, text: str) -> bool:
    if not goal or not text:
        return False
    low = text.lower()
    keys = _goal_keywords(goal)
    if not keys:
        return goal.lower() in low
    matched = sum(1 for k in keys if k.lower() in low)
    return matched >= max(1, len(keys) // 2)


async def run_task(
    db: Session,
    *,
    system_id: str,
    goal: str,
    screen_session_id: Optional[str] = None,
    skill_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    vela_session_id: str = "",
    agent_id: str = "",
    max_steps: int = 6,
    skill_score_threshold: float = 0.55,
    scope: str = "default",
) -> Dict[str, Any]:
    """
    高级任务执行：Observe → Plan(技能检索) → Act(重放/导航) → Verify。
    无法自动完成时返回 needs_agent 供 ReAct Agent 继续。
    """
    params = params or {}
    steps_trace: List[Dict[str, Any]] = []
    sid = screen_session_id

    # Plan: 指定技能或语义检索
    chosen_skill = skill_id
    if not chosen_skill and goal.strip():
        search_res = await search_skills(db, query=goal, scope=scope, top_k=3)
        items = search_res.get("items") or []
        if items and (items[0].get("score") or 0) >= skill_score_threshold:
            chosen_skill = items[0]["skill_id"]
            steps_trace.append({"phase": "plan", "action": "skill_match", "skill_id": chosen_skill, "score": items[0]["score"]})

    # Act: 导航或技能重放
    if not sid:
        nav = await navigate_ui(
            db,
            system_id=system_id,
            url="",
            screen_session_id=None,
            vela_session_id=vela_session_id,
            agent_id=agent_id,
        )
        if nav.get("hitl_pending"):
            return nav
        if not nav.get("success"):
            return nav
        sid = nav.get("screen_session_id", "")
        steps_trace.append({"phase": "act", "action": "navigate", "screen_session_id": sid})

    if chosen_skill and sid:
        replay = await replay_skill(
            db,
            skill_id=chosen_skill,
            screen_session_id=sid,
            params=params,
            vela_session_id=vela_session_id,
            agent_id=agent_id,
        )
        if replay.get("hitl_pending"):
            replay["task_trace"] = steps_trace
            return replay
        steps_trace.append({"phase": "act", "action": "replay_skill", "result": replay.get("success")})
        if not replay.get("success"):
            return {
                **replay,
                "needs_agent": True,
                "task_trace": steps_trace,
                "message": "技能重放失败，需要 Agent 重新规划",
            }

    # Observe + Verify 循环
    for step in range(max_steps):
        obs = await observe_session(db, sid)
        if not obs.get("success"):
            return {**obs, "task_trace": steps_trace}

        steps_trace.append({"phase": "observe", "step": step + 1, "url": obs.get("url"), "elements": len(obs.get("elements") or [])})

        from services.screenpilot.service import extract_ui

        ext = await extract_ui(db, sid)
        page_text = ext.get("text", "") if ext.get("success") else ""

        if _verify_goal(goal, page_text):
            return {
                "success": True,
                "goal_met": True,
                "screen_session_id": sid,
                "message": f"目标已达成: {goal}",
                "task_trace": steps_trace,
                "observe": {"url": obs.get("url"), "element_count": len(obs.get("elements") or [])},
            }

        if chosen_skill:
            break

    skill = skill_store.get_skill(db, chosen_skill) if chosen_skill else None
    return {
        "success": True,
        "goal_met": False,
        "needs_agent": True,
        "screen_session_id": sid,
        "message": "自动规划未能完成目标，请 Agent 基于 observe 结果继续 ui_act",
        "suggested_skill_id": chosen_skill,
        "suggested_skill_name": skill.name if skill else None,
        "task_trace": steps_trace,
        "observe": await observe_session(db, sid) if sid else {},
    }
