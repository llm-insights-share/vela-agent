"""RSN 层 — cu_run_task Observe-Plan-Act-Verify 循环（无 LangGraph，不绕过 HITL）。"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from services.screenpilot.service import navigate_ui, observe_session, replay_skill, search_skills
from services.screenpilot.skill_store import skill_store

logger = logging.getLogger(__name__)

_GOAL_RULE_RE = re.compile(
    r"(?P<key>url_contains|title_contains|text_contains)=(?P<val>[^\s]+)",
    re.IGNORECASE,
)


def _parse_goal_rules(goal: str) -> Tuple[str, Dict[str, str]]:
    """Extract optional url_contains=/title_contains=/text_contains= from goal."""
    rules: Dict[str, str] = {}
    rest = goal or ""
    for m in _GOAL_RULE_RE.finditer(goal or ""):
        rules[m.group("key").lower()] = m.group("val")
        rest = rest.replace(m.group(0), " ")
    return " ".join(rest.split()), rules


def _goal_keywords(goal: str) -> List[str]:
    raw = [w.strip() for w in goal.replace("，", " ").replace(",", " ").split() if w.strip()]
    keys: List[str] = []
    for w in raw:
        if w.lower().startswith(("url_contains=", "title_contains=", "text_contains=")):
            continue
        if len(w) <= 2:
            keys.append(w)
        else:
            keys.extend([w[i : i + 2] for i in range(len(w) - 1)])
    return keys


def _verify_goal_text(goal_text: str, text: str) -> bool:
    if not goal_text or not text:
        return False
    low = text.lower()
    keys = _goal_keywords(goal_text)
    if not keys:
        return goal_text.lower() in low
    matched = sum(1 for k in keys if k.lower() in low)
    return matched >= max(1, len(keys) // 2)


def verify_goal(
    goal: str,
    *,
    page_text: str = "",
    url: str = "",
    title: str = "",
    observe: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Triple check: keywords / URL|title rules / observe structured markers."""
    goal_text, rules = _parse_goal_rules(goal)
    observe = observe or {}
    reasons: List[str] = []

    if rules.get("url_contains"):
        needle = rules["url_contains"].lower()
        if needle in (url or "").lower():
            return {"met": True, "via": "url_contains", "detail": needle}
        reasons.append(f"url_contains 未命中: {needle}")

    if rules.get("title_contains"):
        needle = rules["title_contains"].lower()
        if needle in (title or "").lower():
            return {"met": True, "via": "title_contains", "detail": needle}
        reasons.append(f"title_contains 未命中: {needle}")

    if rules.get("text_contains"):
        needle = rules["text_contains"].lower()
        if needle in (page_text or "").lower():
            return {"met": True, "via": "text_contains", "detail": needle}
        reasons.append(f"text_contains 未命中: {needle}")

    # Structured observe markers often mean unfinished workflow — do not treat as success.
    if observe.get("login_required") or observe.get("risk_blocked"):
        reasons.append("observe 标记 login_required/risk_blocked")

    if goal_text and _verify_goal_text(goal_text, page_text or ""):
        return {"met": True, "via": "page_text_keywords", "detail": goal_text[:80]}

    # If only URL/title rules were specified and none matched, fail closed.
    if rules and not goal_text.strip():
        return {"met": False, "via": None, "reasons": reasons}

    if not goal_text.strip() and not rules:
        return {"met": False, "via": None, "reasons": ["空目标"]}

    return {"met": False, "via": None, "reasons": reasons or ["关键词未覆盖目标"]}


def _build_plan_hints(obs: Dict[str, Any], skill_candidates: Optional[List[Dict]] = None) -> Dict[str, Any]:
    elements = obs.get("elements") or []
    candidates = []
    for e in elements[:12]:
        candidates.append(
            {
                "ref": e.get("ref"),
                "role": e.get("role"),
                "label": (e.get("label") or "")[:40],
            }
        )
    hints: Dict[str, Any] = {
        "url": obs.get("url"),
        "candidate_refs": candidates,
        "login_required": bool(obs.get("login_required")),
        "risk_blocked": bool(obs.get("risk_blocked")),
        "suggest_vision": bool(obs.get("suggest_vision")),
        "form_flow_hint": obs.get("form_flow_hint"),
        "candidate_send_code_refs": obs.get("candidate_send_code_refs"),
    }
    if skill_candidates:
        hints["skill_candidates"] = skill_candidates
    return hints


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
    不会在本层自由 cu_act（避免绕过 HITL）；失败时返回 needs_agent + plan_hints。
    """
    params = params or {}
    steps_trace: List[Dict[str, Any]] = []
    sid = screen_session_id
    skill_candidates: List[Dict[str, Any]] = []

    # Plan: 指定技能或语义检索
    chosen_skill = skill_id
    if not chosen_skill and goal.strip():
        search_res = await search_skills(db, query=goal, scope=scope, top_k=3)
        items = search_res.get("items") or []
        skill_candidates = [
            {"skill_id": i.get("skill_id"), "name": i.get("name"), "score": i.get("score")}
            for i in items
        ]
        if items and (items[0].get("score") or 0) >= skill_score_threshold:
            chosen_skill = items[0]["skill_id"]
            steps_trace.append(
                {
                    "phase": "plan",
                    "action": "skill_match",
                    "skill_id": chosen_skill,
                    "score": items[0]["score"],
                }
            )
        else:
            steps_trace.append(
                {
                    "phase": "plan",
                    "action": "no_skill_match",
                    "candidates": skill_candidates,
                }
            )

    # Act: 导航或技能重放（HITL 仍由 replay_skill / navigate_ui 触发）
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
        steps_trace.append(
            {
                "phase": "act",
                "action": "replay_skill",
                "result": replay.get("success"),
                "needs_replan": bool(replay.get("needs_replan")),
            }
        )
        if not replay.get("success") or replay.get("needs_replan"):
            obs = await observe_session(db, sid) if sid else {}
            return {
                **replay,
                "success": False if not replay.get("success") else True,
                "goal_met": False,
                "needs_agent": True,
                "needs_replan": True,
                "task_trace": steps_trace,
                "plan_hints": _build_plan_hints(obs if isinstance(obs, dict) else {}, skill_candidates),
                "message": "技能重放失败或需要重规划，请 Agent 基于 plan_hints / observe 继续",
                "observe": obs,
            }

    # Observe + Verify 循环（仅校验，不自动点击）
    last_obs: Dict[str, Any] = {}
    last_verify: Dict[str, Any] = {}
    page_title = ""
    for step in range(max(1, int(max_steps or 1))):
        obs = await observe_session(db, sid)
        if not obs.get("success"):
            return {**obs, "task_trace": steps_trace}
        last_obs = obs
        steps_trace.append(
            {
                "phase": "observe",
                "step": step + 1,
                "url": obs.get("url"),
                "elements": len(obs.get("elements") or []),
            }
        )

        from services.screenpilot.service import extract_ui

        ext = await extract_ui(db, sid)
        page_text = ext.get("text", "") if ext.get("success") else ""
        page_title = ""
        try:
            from services.screenpilot.session_manager import get_live_session

            live = get_live_session(sid)
            if live and live.page:
                page_title = await live.page.title()
        except Exception:
            page_title = ""

        last_verify = verify_goal(
            goal,
            page_text=page_text,
            url=obs.get("url") or "",
            title=page_title,
            observe=obs,
        )
        steps_trace.append({"phase": "verify", "step": step + 1, "result": last_verify})

        if last_verify.get("met"):
            return {
                "success": True,
                "goal_met": True,
                "screen_session_id": sid,
                "message": f"目标已达成: {goal}",
                "verify": last_verify,
                "task_trace": steps_trace,
                "observe": {
                    "url": obs.get("url"),
                    "element_count": len(obs.get("elements") or []),
                    "title": page_title,
                },
            }

        # After skill replay we already validated once; further loops only help if URL changes mid-load.
        if chosen_skill and step >= 1:
            break
        if not chosen_skill:
            # No skill to drive the page — hand off immediately after first observe/verify.
            break

    skill = skill_store.get_skill(db, chosen_skill) if chosen_skill else None
    plan_hints = _build_plan_hints(last_obs, skill_candidates)
    host = urlparse(last_obs.get("url") or "").hostname or ""
    if host:
        plan_hints["hostname"] = host

    return {
        "success": True,
        "goal_met": False,
        "needs_agent": True,
        "screen_session_id": sid,
        "message": "自动规划未能完成目标，请 Agent 基于 plan_hints / observe 继续 cu_act（高风险动作仍走 HITL）",
        "suggested_skill_id": chosen_skill,
        "suggested_skill_name": skill.name if skill else None,
        "verify": last_verify,
        "plan_hints": plan_hints,
        "task_trace": steps_trace,
        "observe": last_obs or (await observe_session(db, sid) if sid else {}),
    }
