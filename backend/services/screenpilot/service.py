import base64
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import HITLApproval, ScreenSession, ScreenSystem, SessionStatus, gen_uuid, now_utc
from services.screenpilot.audit import write_audit
from services.screenpilot.layers.act import execute_action
from services.screenpilot.layers.credential import run_login_macro
from services.screenpilot.layers.govern import classify_risk, requires_hitl
from services.screenpilot.layers.ground import find_element_by_ref, build_selector_fingerprint
from services.screenpilot.layers.perceive import build_som, capture_page_state
from services.screenpilot.layers.replay import enrich_fingerprints_from_page, execute_by_fingerprints
from services.screenpilot.session_manager import create_live_session, get_live_session
from services.screenpilot.skill_store import skill_store
from services.screenpilot.trajectory import (
    append_trajectory_step,
    compile_trajectory_to_skill,
    resolve_template,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _get_system(db: Session, system_id: str) -> Optional[ScreenSystem]:
    return db.query(ScreenSystem).filter(ScreenSystem.system_id == system_id).first()


def _resolve_screen_session(
    db: Session,
    *,
    screen_session_id: Optional[str],
    system_id: str,
    vela_session_id: str = "",
    agent_id: str = "",
) -> ScreenSession:
    if screen_session_id:
        row = (
            db.query(ScreenSession)
            .filter(ScreenSession.screen_session_id == screen_session_id)
            .first()
        )
        if row:
            return row

    row = ScreenSession(
        screen_session_id=gen_uuid(),
        system_id=system_id,
        vela_session_id=vela_session_id or "",
        agent_id=agent_id or "",
        status="ACTIVE",
        meta={},
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def observe_session(db: Session, screen_session_id: str) -> Dict[str, Any]:
    live = get_live_session(screen_session_id)
    if not live:
        return {"success": False, "error": f"浏览器会话不存在: {screen_session_id}"}

    row = db.query(ScreenSession).filter(
        ScreenSession.screen_session_id == screen_session_id
    ).first()

    if getattr(live, "exec_mode", "browser") == "desktop":
        from services.screenpilot.layers.desktop import capture_screenshot_png, desktop_available

        if not desktop_available():
            return {"success": False, "error": "桌面模式需要 DISPLAY 或 Xvfb 环境"}
        shot = capture_screenshot_png()
        hotspots = (live.desktop_macro or {}).get("hotspots") or {}
        elements = [
            {
                "ref": f"[{i + 1}]",
                "role": "hotspot",
                "label": name,
                "box": {
                    "x": int(hs.get("x", 0)),
                    "y": int(hs.get("y", 0)),
                    "width": int(hs.get("width", 20)),
                    "height": int(hs.get("height", 20)),
                },
            }
            for i, (name, hs) in enumerate(hotspots.items())
        ]
        live.elements = elements
        live.last_screenshot = shot
        live.last_som_image = shot

        if row:
            row.current_url = "desktop://"
            row.updated_at = now_utc()
            db.commit()

        write_audit(
            db,
            screen_session_id=screen_session_id,
            vela_session_id=row.vela_session_id if row else "",
            agent_id=row.agent_id if row else "",
            action="observe",
            risk_tier="T0",
            screenshot_png=shot,
            payload={"mode": "desktop", "element_count": len(elements)},
        )
        return {
            "success": True,
            "screen_session_id": screen_session_id,
            "url": "desktop://",
            "exec_mode": "desktop",
            "screenshot_b64": _b64(shot),
            "som_image_b64": _b64(shot),
            "elements": elements,
        }

    shot, tree, url = await capture_page_state(live.page)
    som_img, elements = build_som(shot, tree)
    live.elements = elements
    live.last_screenshot = shot
    live.last_som_image = som_img

    row = db.query(ScreenSession).filter(
        ScreenSession.screen_session_id == screen_session_id
    ).first()
    if row:
        row.current_url = url
        row.updated_at = now_utc()
        db.commit()

    write_audit(
        db,
        screen_session_id=screen_session_id,
        vela_session_id=row.vela_session_id if row else "",
        agent_id=row.agent_id if row else "",
        action="observe",
        risk_tier="T0",
        screenshot_png=shot,
        payload={"url": url, "element_count": len(elements)},
    )

    return {
        "success": True,
        "screen_session_id": screen_session_id,
        "url": url,
        "screenshot_b64": _b64(shot),
        "som_image_b64": _b64(som_img),
        "elements": elements,
    }


async def navigate_ui(
    db: Session,
    *,
    system_id: str,
    url: str,
    screen_session_id: Optional[str] = None,
    vela_session_id: str = "",
    agent_id: str = "",
    auto_login: bool = True,
) -> Dict[str, Any]:
    system = _get_system(db, system_id)
    if not system:
        return {"success": False, "error": f"系统未注册: {system_id}"}

    row = _resolve_screen_session(
        db,
        screen_session_id=screen_session_id,
        system_id=system_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
    )
    target_url = url or system.entry_url
    desktop_macro = (system.login_macro or {}).get("desktop") or {}
    live = await create_live_session(
        row.screen_session_id,
        system_id,
        exec_mode=system.exec_mode or "browser",
        desktop_macro=desktop_macro,
    )

    if (system.exec_mode or "browser") == "desktop":
        obs = await observe_session(db, row.screen_session_id)
        obs["screen_session_id"] = row.screen_session_id
        return obs

    allowed = system.allowed_domains or []

    if auto_login and system.login_macro:
        login_result = await run_login_macro(live.page, system, db)
        if not login_result.get("success"):
            return login_result

    if target_url:
        nav = await execute_action(
            live.page, "navigate", [], value=target_url, allowed_domains=allowed
        )
        if not nav.get("success"):
            return nav

    obs = await observe_session(db, row.screen_session_id)
    obs["screen_session_id"] = row.screen_session_id
    return obs


def create_hitl_for_ui_action(
    db: Session,
    *,
    screen_session_id: str,
    vela_session_id: str,
    agent_id: str,
    tool_name: str,
    action_payload: Dict[str, Any],
    preview_payload: Dict[str, Any],
    risk_tier: str,
) -> HITLApproval:
    from models import Session as AgentSession

    approval = HITLApproval(
        approval_id=gen_uuid(),
        session_id=vela_session_id,
        agent_id=agent_id,
        tool_name=tool_name,
        tool_args={
            **action_payload,
            "screen_session_id": screen_session_id,
            "preview_payload": preview_payload,
            "risk_tier": risk_tier,
            "deferred": True,
        },
        status="PENDING",
        created_at=now_utc(),
    )
    db.add(approval)

    sess = db.query(AgentSession).filter(
        AgentSession.session_id == vela_session_id
    ).first()
    if sess:
        sess.status = SessionStatus.HITL_WAIT

    db.commit()
    db.refresh(approval)

    # P2: T3 走 Vela 内置审批流（平台收件箱 + 会话 HITL）
    if risk_tier == "T3":
        from services.screenpilot.internal_approval import mark_t3_internal_flow

        approval.tool_args = mark_t3_internal_flow(approval.tool_args or {})
        db.commit()

    return approval


async def act_ui(
    db: Session,
    *,
    screen_session_id: str,
    action: str,
    target_ref: Optional[str] = None,
    value: Optional[str] = None,
    vela_session_id: str = "",
    agent_id: str = "",
    force_execute: bool = False,
) -> Dict[str, Any]:
    live = get_live_session(screen_session_id)
    if not live:
        row = db.query(ScreenSession).filter(
            ScreenSession.screen_session_id == screen_session_id
        ).first()
        if not row:
            return {"success": False, "error": f"浏览器会话不存在: {screen_session_id}"}
        system = _get_system(db, row.system_id)
        desktop_macro = ((system.login_macro or {}).get("desktop") if system else {}) or {}
        live = await create_live_session(
            screen_session_id,
            row.system_id,
            exec_mode=(system.exec_mode if system else "browser") or "browser",
            desktop_macro=desktop_macro,
        )

    row = db.query(ScreenSession).filter(
        ScreenSession.screen_session_id == screen_session_id
    ).first()
    system = _get_system(db, row.system_id) if row else None
    allowed = (system.allowed_domains or []) if system else []
    risk_rules = (system.risk_rules or {}) if system else {}

    if getattr(live, "exec_mode", "browser") == "desktop":
        from services.screenpilot.layers.desktop import execute_desktop_action

        target_label = target_ref or ""
        if target_ref and live.elements:
            el = find_element_by_ref(live.elements, target_ref)
            if el:
                target_label = el.get("label") or target_ref

        risk_tier = classify_risk(action, target_label, risk_rules)
        if requires_hitl(risk_tier) and not force_execute:
            preview = {
                "action": action,
                "target_ref": target_ref,
                "value": value,
                "risk_tier": risk_tier,
                "target_label": target_label,
                "url": "desktop://",
                "exec_mode": "desktop",
            }
            if live.last_screenshot:
                preview["screenshot_b64"] = _b64(live.last_screenshot)
            approval = create_hitl_for_ui_action(
                db,
                screen_session_id=screen_session_id,
                vela_session_id=vela_session_id or (row.vela_session_id if row else ""),
                agent_id=agent_id or (row.agent_id if row else ""),
                tool_name="ui_act",
                action_payload={"action": action, "target_ref": target_ref, "value": value},
                preview_payload=preview,
                risk_tier=risk_tier,
            )
            return {
                "success": True,
                "hitl_pending": True,
                "approval_id": approval.approval_id,
                "risk_tier": risk_tier,
                "preview_payload": preview,
                "message": f"桌面动作 [{action}] 风险 {risk_tier}，等待审批",
            }

        result = await execute_desktop_action(
            action,
            target_ref=target_ref,
            value=value,
            desktop_macro=live.desktop_macro,
        )
        if not result.get("success"):
            return result
        obs = await observe_session(db, screen_session_id)
        return {
            "success": True,
            "risk_tier": risk_tier,
            "exec_mode": "desktop",
            "verification": result,
            "observe": {"url": obs.get("url"), "elements": obs.get("elements")},
        }

    target_label = ""
    if target_ref and live.elements:
        from services.screenpilot.layers.ground import find_element_by_ref

        el = find_element_by_ref(live.elements, target_ref)
        if el:
            target_label = el.get("label") or ""

    risk_tier = classify_risk(action, target_label, risk_rules)

    if requires_hitl(risk_tier) and not force_execute:
        preview = {
            "action": action,
            "target_ref": target_ref,
            "value": value,
            "risk_tier": risk_tier,
            "target_label": target_label,
            "url": live.page.url if live.page else "",
        }
        if live.last_som_image:
            preview["som_image_b64"] = _b64(live.last_som_image)
        elif live.last_screenshot:
            preview["screenshot_b64"] = _b64(live.last_screenshot)

        approval = create_hitl_for_ui_action(
            db,
            screen_session_id=screen_session_id,
            vela_session_id=vela_session_id or (row.vela_session_id if row else ""),
            agent_id=agent_id or (row.agent_id if row else ""),
            tool_name="ui_act",
            action_payload={
                "action": action,
                "target_ref": target_ref,
                "value": value,
            },
            preview_payload=preview,
            risk_tier=risk_tier,
        )

        write_audit(
            db,
            screen_session_id=screen_session_id,
            vela_session_id=vela_session_id,
            agent_id=agent_id,
            action=f"hitl_gate:{action}",
            risk_tier=risk_tier,
            payload={"target_ref": target_ref, "target_label": target_label},
            screenshot_png=live.last_screenshot or None,
            approval_id=approval.approval_id,
        )

        return {
            "success": True,
            "hitl_pending": True,
            "approval_id": approval.approval_id,
            "risk_tier": risk_tier,
            "preview_payload": preview,
            "message": (
                f"动作 [{action}] 风险等级 {risk_tier}，已创建审批工单"
                + ("，请在「驭屏审批」收件箱或会话中处理" if risk_tier == "T3" else "，等待 HITL 审批")
            ),
        }

    result = await execute_action(
        live.page,
        action,
        live.elements,
        target_ref=target_ref,
        value=value,
        allowed_domains=allowed,
    )
    if not result.get("success"):
        return result

    obs = await observe_session(db, screen_session_id)

    target_el = result.get("target")
    if target_el and live.page:
        fingerprints = await enrich_fingerprints_from_page(live.page, target_el)
    elif target_ref and live.elements:
        el = find_element_by_ref(live.elements, target_ref)
        fingerprints = await enrich_fingerprints_from_page(live.page, el) if el and live.page else build_selector_fingerprint(el or {})
    else:
        fingerprints = {}

    append_trajectory_step(
        db,
        screen_session_id,
        {
            "action": action,
            "target_ref": target_ref,
            "target_label": target_label,
            "value": value,
            "url": live.page.url if live.page else "",
            "role": (target_el or {}).get("role", ""),
            "target": target_el,
            "fingerprints": fingerprints,
            "risk_tier": risk_tier,
        },
    )

    write_audit(
        db,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id or (row.vela_session_id if row else ""),
        agent_id=agent_id or (row.agent_id if row else ""),
        action=action,
        risk_tier=risk_tier,
        payload={"target_ref": target_ref, "value": value},
        screenshot_png=live.last_screenshot or None,
        verification=result.get("verification"),
    )

    return {
        "success": True,
        "risk_tier": risk_tier,
        "verification": result.get("verification"),
        "observe": {
            "url": obs.get("url"),
            "elements": obs.get("elements"),
            "som_image_b64": obs.get("som_image_b64"),
        },
    }


async def extract_ui(db: Session, screen_session_id: str) -> Dict[str, Any]:
    live = get_live_session(screen_session_id)
    if not live:
        return {"success": False, "error": f"浏览器会话不存在: {screen_session_id}"}
    if getattr(live, "exec_mode", "browser") == "desktop":
        return {
            "success": True,
            "text": "",
            "exec_mode": "desktop",
            "message": "桌面模式暂不支持文本提取，请使用 observe 截图",
        }
    text = await live.page.inner_text("body")
    return {"success": True, "text": (text or "")[:8000]}


async def replay_skill(
    db: Session,
    *,
    skill_id: str,
    screen_session_id: str,
    params: Optional[Dict[str, Any]] = None,
    vela_session_id: str = "",
    agent_id: str = "",
    force_execute: bool = False,
) -> Dict[str, Any]:
    """确定性重放 UI 技能；指纹失效时返回 needs_replan。"""
    skill = skill_store.get_skill(db, skill_id)
    if not skill:
        return {"success": False, "error": f"技能不存在: {skill_id}"}

    steps = skill_store.get_steps(db, skill_id)
    if not steps:
        return {"success": False, "error": "技能无步骤"}

    live = get_live_session(screen_session_id)
    system = _get_system(db, skill.system_id)
    if not live:
        row = db.query(ScreenSession).filter(
            ScreenSession.screen_session_id == screen_session_id
        ).first()
        if not row:
            return {"success": False, "error": f"浏览器会话不存在: {screen_session_id}"}
        desktop_macro = ((system.login_macro or {}).get("desktop") if system else {}) or {}
        live = await create_live_session(
            screen_session_id,
            row.system_id,
            exec_mode=(system.exec_mode if system else "browser") or "browser",
            desktop_macro=desktop_macro,
        )

    risk_rules = (system.risk_rules or {}) if system else {}
    params = params or {}
    results = []

    for step in steps:
        value = resolve_template(step.value_template or "", params)
        action = step.action
        label = step.target_label or ""
        risk_tier = classify_risk(action, label, risk_rules)

        if requires_hitl(risk_tier) and not force_execute:
            preview = {
                "action": action,
                "target_label": label,
                "value": value,
                "risk_tier": risk_tier,
                "skill_id": skill_id,
                "step_order": step.step_order,
            }
            approval = create_hitl_for_ui_action(
                db,
                screen_session_id=screen_session_id,
                vela_session_id=vela_session_id,
                agent_id=agent_id,
                tool_name="ui_replay_skill",
                action_payload={
                    "skill_id": skill_id,
                    "screen_session_id": screen_session_id,
                    "step_id": step.step_id,
                    "params": params,
                    "resume_from_step": step.step_order,
                },
                preview_payload=preview,
                risk_tier=risk_tier,
            )
            return {
                "success": True,
                "hitl_pending": True,
                "approval_id": approval.approval_id,
                "risk_tier": risk_tier,
                "preview_payload": preview,
                "completed_steps": len(results),
                "message": f"重放步骤 {step.step_order} 触发 {risk_tier} HITL",
            }

        if action == "navigate" and value:
            allowed = (system.allowed_domains or []) if system else []
            nav = await execute_action(live.page, "navigate", [], value=value, allowed_domains=allowed)
            exec_result = nav
        else:
            exec_result = await execute_by_fingerprints(
                live.page, action, step.fingerprints or {}, value=value
            )

        if not exec_result.get("success"):
            if exec_result.get("needs_replan"):
                return {
                    "success": False,
                    "error": exec_result.get("error", "指纹定位失效"),
                    "needs_replan": True,
                    "failed_step": step.step_order,
                    "completed_steps": results,
                }
            return exec_result

        results.append(
            {
                "step_order": step.step_order,
                "action": action,
                "locate_method": exec_result.get("locate_method"),
                "verification": exec_result.get("verification"),
            }
        )

        if step.fingerprints and exec_result.get("locate_method"):
            updated = dict(step.fingerprints)
            updated["last_method"] = exec_result.get("locate_method")
            skill_store.update_step_fingerprints(db, step.step_id, updated)

    await observe_session(db, screen_session_id)
    write_audit(
        db,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
        action="replay_skill",
        risk_tier="T1",
        payload={"skill_id": skill_id, "steps": len(results)},
    )
    return {
        "success": True,
        "skill_id": skill_id,
        "replayed_steps": len(results),
        "results": results,
    }


async def compile_skill(
    db: Session,
    *,
    screen_session_id: str,
    name: str,
    description: str = "",
    scope: str = "default",
) -> Dict[str, Any]:
    return compile_trajectory_to_skill(
        db,
        screen_session_id=screen_session_id,
        name=name,
        description=description,
        scope=scope,
    )


async def search_skills(
    db: Session,
    *,
    query: str,
    scope: str = "default",
    top_k: int = 5,
) -> Dict[str, Any]:
    matches = skill_store.search(query, scope=scope, top_k=top_k, db=db)
    items = []
    for skill_id, score in matches:
        skill = skill_store.get_skill(db, skill_id)
        if skill and skill.status == "ACTIVE":
            items.append(
                {
                    "skill_id": skill_id,
                    "name": skill.name,
                    "description": skill.description,
                    "system_id": skill.system_id,
                    "score": score,
                }
            )
    return {"success": True, "items": items}


async def execute_deferred_ui_act(db: Session, approval: HITLApproval) -> str:
    """HITL 批准后执行挂起的 ui_act 或 ui_replay_skill。"""
    args = approval.tool_args or {}
    if approval.tool_name == "ui_replay_skill" and args.get("skill_id"):
        result = await replay_skill(
            db,
            skill_id=args["skill_id"],
            screen_session_id=args.get("screen_session_id", ""),
            params=args.get("params") or {},
            vela_session_id=approval.session_id,
            agent_id=approval.agent_id,
            force_execute=True,
        )
        return json.dumps(result, ensure_ascii=False)

    screen_session_id = args.get("screen_session_id", "")
    result = await act_ui(
        db,
        screen_session_id=screen_session_id,
        action=args.get("action", "click"),
        target_ref=args.get("target_ref"),
        value=args.get("value"),
        vela_session_id=approval.session_id,
        agent_id=approval.agent_id,
        force_execute=True,
    )
    return json.dumps(result, ensure_ascii=False)


async def run_workflow_screenpilot(
    db: Session,
    *,
    operation: str,
    system_id: str = "",
    screen_session_id: str = "",
    skill_id: str = "",
    params: Optional[Dict[str, Any]] = None,
    url: str = "",
    action: str = "",
    target_ref: str = "",
    value: str = "",
    vela_session_id: str = "",
    agent_id: str = "",
) -> Dict[str, Any]:
    """Workflow ScreenPilot 节点：直接调用服务层（不经 MCP）。"""
    op = (operation or "navigate").lower()
    params = params or {}

    if op == "navigate":
        return await navigate_ui(
            db,
            system_id=system_id,
            url=url,
            screen_session_id=screen_session_id or None,
            vela_session_id=vela_session_id,
            agent_id=agent_id,
        )
    if op == "observe":
        if not screen_session_id:
            return {"success": False, "error": "observe 需要 screen_session_id"}
        return await observe_session(db, screen_session_id)
    if op == "extract":
        if not screen_session_id:
            return {"success": False, "error": "extract 需要 screen_session_id"}
        return await extract_ui(db, screen_session_id)
    if op == "replay":
        if not skill_id or not screen_session_id:
            return {"success": False, "error": "replay 需要 skill_id 与 screen_session_id"}
        return await replay_skill(
            db,
            skill_id=skill_id,
            screen_session_id=screen_session_id,
            params=params,
            vela_session_id=vela_session_id,
            agent_id=agent_id,
        )
    if op == "act":
        if not screen_session_id:
            return {"success": False, "error": "act 需要 screen_session_id"}
        return await act_ui(
            db,
            screen_session_id=screen_session_id,
            action=action or "click",
            target_ref=target_ref or None,
            value=value or None,
            vela_session_id=vela_session_id,
            agent_id=agent_id,
        )
    if op == "run_task":
        from services.screenpilot.run_task import run_task

        return await run_task(
            db,
            system_id=system_id,
            goal=params.get("goal") or "",
            screen_session_id=screen_session_id or None,
            skill_id=params.get("skill_id") or skill_id or None,
            params=params,
            vela_session_id=vela_session_id,
            agent_id=agent_id,
        )

    return {"success": False, "error": f"未知 ScreenPilot 操作: {operation}"}


TOOL_HANDLERS = {
    "ui_navigate": navigate_ui,
    "ui_observe": lambda db, **kw: observe_session(db, kw["screen_session_id"]),
    "ui_act": act_ui,
    "ui_extract": lambda db, **kw: extract_ui(db, kw["screen_session_id"]),
    "ui_replay_skill": replay_skill,
    "ui_compile_skill": compile_skill,
    "ui_search_skills": search_skills,
}
