import base64
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import HITLApproval, ScreenSession, ScreenSystem, SessionStatus, gen_uuid, now_utc
from services.screenpilot.audit import write_audit
from services.screenpilot.layers.act import execute_action
from services.screenpilot.layers.credential import run_login_macro, resume_login_macro_after_otp
from services.screenpilot.cookie_store import get_valid_storage_state, save_storage_state
from services.screenpilot.layers.govern import (
    classify_risk,
    requires_hitl,
    check_domain_allowed,
    check_navigation_allowed,
)
from services.screenpilot.layers.ground import find_element_by_ref, build_selector_fingerprint
from services.screenpilot.layers.perceive import (
    DEFAULT_MAX_ELEMENTS,
    build_login_form_hint,
    build_som,
    capture_page_state,
    collect_dom_elements,
    detect_login_wall,
    detect_risk_block,
    extract_a11y_elements,
    prepare_som_elements,
)
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
    """按 system_id（UUID）或系统名称解析已激活系统。"""
    key = (system_id or "").strip()
    if not key:
        return None
    by_id = (
        db.query(ScreenSystem)
        .filter(ScreenSystem.system_id == key, ScreenSystem.status == "ACTIVE")
        .first()
    )
    if by_id:
        return by_id
    return (
        db.query(ScreenSystem)
        .filter(ScreenSystem.name == key, ScreenSystem.status == "ACTIVE")
        .first()
    )


def _system_lookup_error(db: Session, system_id: str) -> Dict[str, Any]:
    key = (system_id or "").strip()
    raw = (
        db.query(ScreenSystem)
        .filter((ScreenSystem.system_id == key) | (ScreenSystem.name == key))
        .first()
    )
    if raw and raw.status != "ACTIVE":
        return {"success": False, "error": f"系统已停用: {key}"}
    available = [
        {"system_id": r.system_id, "name": r.name}
        for r in db.query(ScreenSystem).filter(ScreenSystem.status == "ACTIVE").all()
    ]
    hint = (
        "；可用系统: " + ", ".join(f"{a['name']}({a['system_id']})" for a in available)
        if available
        else "；当前无已激活系统，请先在驭屏系统管理中注册"
    )
    return {"success": False, "error": f"系统未注册: {key}{hint}"}


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


async def _open_live_browser_session(
    db: Session,
    *,
    screen_session_id: str,
    system_id: str,
    system: Optional[ScreenSystem] = None,
) -> Any:
    """获取或创建浏览器 LiveSession，优先恢复已持久化的 cookie（24h 内有效）。"""
    sys = system or _get_system(db, system_id)
    desktop_macro = ((sys.login_macro or {}).get("desktop") if sys else {}) or {}
    storage_state = get_valid_storage_state(db, system_id)
    return await create_live_session(
        screen_session_id,
        system_id,
        exec_mode=(sys.exec_mode if sys else "browser") or "browser",
        desktop_macro=desktop_macro,
        storage_state=storage_state,
    )


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
    a11y_els = extract_a11y_elements(tree)
    dom_els, dialogs = await collect_dom_elements(live.page, limit=max(DEFAULT_MAX_ELEMENTS * 2, 200))
    ranked, som_meta = prepare_som_elements(
        a11y_els, dom_els, dialogs, max_elements=DEFAULT_MAX_ELEMENTS
    )
    som_source = som_meta.get("som_source") or "empty"
    som_img, elements = build_som(shot, {}, extra_elements=ranked)
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
        payload={
            "url": url,
            "element_count": len(elements),
            "som_source": som_source,
            "total_elements": som_meta.get("total_elements"),
            "truncated": som_meta.get("truncated"),
            "scope": som_meta.get("scope"),
        },
    )

    body_preview = ""
    try:
        body_preview = await live.page.inner_text("body")
    except Exception:
        body_preview = ""
    login_wall = detect_login_wall(body_preview)
    system = _get_system(db, row.system_id) if row else None
    risk_rules = (system.risk_rules or {}) if system else {}
    risk = detect_risk_block(body_preview, url, risk_rules=risk_rules)
    result = {
        "success": True,
        "screen_session_id": screen_session_id,
        "url": url,
        "screenshot_b64": _b64(shot),
        "som_image_b64": _b64(som_img),
        "elements": elements,
        "som_source": som_source,
        "total_elements": som_meta.get("total_elements", len(elements)),
        "truncated": bool(som_meta.get("truncated")),
        "scope": som_meta.get("scope") or "page",
    }
    login_form = build_login_form_hint(elements)
    if login_form:
        result["login_form_hint"] = login_form
    if risk:
        result["risk_blocked"] = True
        result["error_code"] = risk["error_code"]
        result["warning"] = (
            f"{risk['message']}（error_code={risk['error_code']}）。"
            "请按系统 risk_rules / entry_url 配置调整网络或入口后重试。"
        )
        result["recovery_hint"] = str(
            risk_rules.get("recovery_hint")
            or "检查网络环境与系统 entry_url / risk_rules 配置后重试"
        )
    elif login_wall:
        result["warning"] = (
            "页面疑似登录墙/未登录态：搜索与个性化内容可能不可用。"
            "请先完成登录，或设置 auto_login=true 并配置登录宏。"
        )
        result["login_required"] = True

    # Structural SMS/login form hint (no site-specific vocabulary).
    textboxes = [
        e for e in elements
        if (e.get("role") or "").lower() in ("textbox", "searchbox")
    ]

    def _row_near_textbox(btn: Dict[str, Any]) -> bool:
        bb = btn.get("box") or {}
        bw = float(bb.get("width") or 0)
        # Full-width primary submit buttons are not send-code controls.
        if bw > 180:
            return False
        by = float(bb.get("y") or 0)
        bh = float(bb.get("height") or 0)
        bcy = by + bh / 2
        bx1 = float(bb.get("x") or 0)
        bx2 = bx1 + bw
        for tb in textboxes:
            tbx = tb.get("box") or {}
            ty = float(tbx.get("y") or 0)
            th = float(tbx.get("height") or 0)
            tcy = ty + th / 2
            if abs(bcy - tcy) > 36:
                continue
            tx1 = float(tbx.get("x") or 0)
            tx2 = tx1 + float(tbx.get("width") or 0)
            gap = max(0.0, max(bx1 - tx2, tx1 - bx2))
            overlap = min(bx2, tx2) - max(bx1, tx1)
            if gap <= 56 or overlap > 0:
                return True
        return False

    send_code_candidates = [
        e for e in elements
        if (e.get("role") or "").lower() in ("button", "link")
        and 1 <= len((e.get("label") or "").strip()) <= 16
        and _row_near_textbox(e)
    ]
    # Exclude labels that also appear as wide primary buttons (e.g. duplicate "登录").
    wide_labels = {
        ((e.get("label") or "").strip())
        for e in elements
        if (e.get("role") or "").lower() in ("button", "link")
        and float((e.get("box") or {}).get("width") or 0) > 180
    }
    send_code_candidates = [
        e for e in send_code_candidates
        if (e.get("label") or "").strip() not in wide_labels
    ]
    short_btns = send_code_candidates  # for debug log compatibility
    if send_code_candidates and textboxes:
        cand_txt = ", ".join(
            f"{e.get('ref')}={(e.get('label') or '')[:12]}/{e.get('role')}"
            for e in send_code_candidates[:4]
        )
        result["form_flow_hint"] = (
            "检测到输入框旁的短按钮/链接：填入手机号后必须先点击该控件请求验证码"
            "（可能是 button 或 link），确认文案变为倒计时后再填验证码并点主提交。"
            "等待用户短信请调用 cu_wait_for_otp，不要对 cu_act wait 传入 otp/code。"
            f"候选发码控件: {cand_txt}"
        )
        result["candidate_send_code_refs"] = [e.get("ref") for e in send_code_candidates[:6]]

    # Vision fallback hint: sparse SoM or canvas-heavy page (agent may call cu_vision).
    canvas_count = 0
    try:
        canvas_count = int(
            await live.page.evaluate("() => document.querySelectorAll('canvas').length") or 0
        )
    except Exception:
        canvas_count = 0
    sparse = len(elements) < 3 or som_source in ("empty", "")
    if sparse or canvas_count > 0:
        result["suggest_vision"] = True
        result["vision_hint"] = (
            "可访问性/DOM 元素偏少或存在 canvas，建议调用 cu_vision 用截图回答布局问题"
            if sparse
            else "页面含 canvas，SoM 可能不可靠，建议在必要时调用 cu_vision"
        )
        result["canvas_count"] = canvas_count

    return result


def _resolve_navigate_url(system: ScreenSystem, url: str, allowed: List[str]) -> str:
    """Resolve target URL; fall back to entry_url when LLM uses a non-whitelisted host."""
    from urllib.parse import urljoin, urlparse

    raw = (url or "").strip()
    entry = (system.entry_url or "").strip()
    if not raw:
        return entry
    if not raw.startswith(("http://", "https://")):
        if entry:
            entry_parsed = urlparse(entry)
            segment = raw.lstrip("/")
            entry_path = entry_parsed.path.rstrip("/")
            if entry_path == f"/{segment}" or entry_path.endswith(f"/{segment}"):
                return entry
            base = f"{entry_parsed.scheme}://{entry_parsed.netloc}"
            return urljoin(base.rstrip("/") + "/", segment)
        return raw
    if not allowed or check_domain_allowed(raw, allowed):
        return raw
    if entry and check_domain_allowed(entry, allowed):
        parsed = urlparse(raw)
        if parsed.path and parsed.path not in ("", "/"):
            entry_base = f"{urlparse(entry).scheme}://{urlparse(entry).netloc}"
            mapped = urljoin(entry_base.rstrip("/") + "/", parsed.path.lstrip("/"))
            if check_domain_allowed(mapped, allowed):
                return mapped
        return entry
    return raw


async def navigate_ui(
    db: Session,
    *,
    system_id: str,
    url: str = "",
    screen_session_id: Optional[str] = None,
    vela_session_id: str = "",
    agent_id: str = "",
    auto_login: bool = True,
) -> Dict[str, Any]:
    system = _get_system(db, system_id)
    if not system:
        return _system_lookup_error(db, system_id)

    resolved_id = system.system_id
    row = _resolve_screen_session(
        db,
        screen_session_id=screen_session_id,
        system_id=resolved_id,
        vela_session_id=vela_session_id,
        agent_id=agent_id,
    )
    target_url = _resolve_navigate_url(system, url, system.allowed_domains or [])
    if target_url:
        ok_nav, reason_nav = check_navigation_allowed(
            target_url, system.allowed_domains or []
        )
        if not ok_nav:
            return {"success": False, "error": reason_nav, "url": target_url}

    live = await _open_live_browser_session(
        db,
        screen_session_id=row.screen_session_id,
        system_id=resolved_id,
        system=system,
    )

    if (system.exec_mode or "browser") == "desktop":
        obs = await observe_session(db, row.screen_session_id)
        obs["screen_session_id"] = row.screen_session_id
        obs["system_id"] = resolved_id
        obs["system_name"] = system.name
        return obs

    allowed = system.allowed_domains or []

    skip_login = False
    if auto_login and get_valid_storage_state(db, resolved_id):
        check_url = target_url or system.entry_url
        if check_url and live.page:
            await execute_action(
                live.page, "navigate", [], value=check_url, allowed_domains=allowed
            )
            probe = await observe_session(db, row.screen_session_id)
            if probe.get("success") and not probe.get("login_required"):
                skip_login = True

    if auto_login and not skip_login:
        macro_steps = ((system.login_macro or {}).get("steps") or []) if system else []
        if macro_steps:
            login_result = await run_login_macro(
                live.page,
                system,
                db,
                screen_session_id=row.screen_session_id,
                vela_session_id=vela_session_id or row.vela_session_id,
                agent_id=agent_id or row.agent_id,
            )
            if login_result.get("hitl_pending"):
                login_result["screen_session_id"] = row.screen_session_id
                login_result["system_id"] = resolved_id
                login_result["system_name"] = system.name
                return login_result
            if not login_result.get("success"):
                return login_result
            if live.context:
                await save_storage_state(db, resolved_id, live.context)
        else:
            # No login_macro steps: fill vault credentials on login page via SoM.
            probe = await observe_session(db, row.screen_session_id)
            if probe.get("success") and (
                probe.get("login_required")
                or build_login_form_hint(probe.get("elements") or [])
            ):
                from services.screenpilot.layers.credential import (
                    auto_fill_login_from_credentials,
                )

                fill = await auto_fill_login_from_credentials(
                    live.page,
                    db,
                    system_id=resolved_id,
                    elements=probe.get("elements") or live.elements or [],
                )
                if fill.get("success") and live.context:
                    await save_storage_state(db, resolved_id, live.context)

    if target_url:
        nav = await execute_action(
            live.page, "navigate", [], value=target_url, allowed_domains=allowed
        )
        if not nav.get("success"):
            return nav

    obs = await observe_session(db, row.screen_session_id)
    obs["screen_session_id"] = row.screen_session_id
    obs["system_id"] = resolved_id
    obs["system_name"] = system.name
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


def create_hitl_for_login_otp(
    db: Session,
    *,
    screen_session_id: str,
    vela_session_id: str,
    agent_id: str,
    prompt: str,
    preview_payload: Dict[str, Any],
    login_macro_resume: Optional[Dict[str, Any]] = None,
    otp_action: Optional[Dict[str, Any]] = None,
) -> HITLApproval:
    """登录宏 wait_for_otp 或 cu_wait_for_otp：等待用户输入验证码。"""
    from models import Session as AgentSession

    tool_args = {
        "flow_kind": "otp_wait",
        "screen_session_id": screen_session_id,
        "preview_payload": preview_payload,
        "prompt": prompt,
    }
    if login_macro_resume:
        tool_args["login_macro_resume"] = login_macro_resume
    if otp_action:
        tool_args["otp_action"] = otp_action

    approval = HITLApproval(
        approval_id=gen_uuid(),
        session_id=vela_session_id,
        agent_id=agent_id,
        tool_name="cu_login_otp",
        tool_args=tool_args,
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
    return approval


async def resume_login_after_otp_approval(
    db: Session,
    approval: HITLApproval,
    otp_code: str,
) -> str:
    """HITL 验证码提交后恢复登录流程。"""
    tool_args = approval.tool_args or {}
    screen_session_id = tool_args.get("screen_session_id") or ""
    live = get_live_session(screen_session_id)
    if not live or not live.page:
        row = db.query(ScreenSession).filter(
            ScreenSession.screen_session_id == screen_session_id
        ).first()
        if not row:
            return "浏览器会话不存在"
        system = _get_system(db, row.system_id)
        if not system:
            return "系统不存在"
        live = await _open_live_browser_session(
            db,
            screen_session_id=screen_session_id,
            system_id=row.system_id,
            system=system,
        )

    row = db.query(ScreenSession).filter(
        ScreenSession.screen_session_id == screen_session_id
    ).first()
    if not row:
        return "浏览器会话记录不存在"

    system = _get_system(db, row.system_id)
    if not system:
        return "系统不存在"

    resume = tool_args.get("login_macro_resume")
    otp_action = tool_args.get("otp_action") or {}
    selector = (otp_action.get("selector") or "").strip()
    submit_selector = (otp_action.get("submit_selector") or "").strip()
    url_before = ""
    try:
        url_before = live.page.url if live and live.page else ""
    except Exception:
        url_before = ""
    if resume:
        result = await resume_login_macro_after_otp(
            live.page,
            system,
            db,
            otp_code=otp_code,
            resume=resume,
            screen_session_id=screen_session_id,
            vela_session_id=approval.session_id,
            agent_id=approval.agent_id,
        )
    else:
        fill_ok = False
        click_ok = False
        fill_err = ""
        click_err = ""
        if selector:
            try:
                await live.page.fill(selector, otp_code)
                fill_ok = True
            except Exception as e:
                fill_err = str(e)[:200]
        if submit_selector:
            try:
                await live.page.click(submit_selector)
                click_ok = True
            except Exception as e:
                click_err = str(e)[:200]
        result = {
            "success": True if (not selector or fill_ok) else False,
            "message": "验证码已提交",
            "url": live.page.url,
            "fill_ok": fill_ok,
            "click_ok": click_ok,
            "fill_skipped": not bool(selector),
            "click_skipped": not bool(submit_selector),
            "fill_err": fill_err,
            "click_err": click_err,
        }

    if result.get("hitl_pending"):
        return json.dumps(result, ensure_ascii=False)

    if result.get("success") and live.context:
        await save_storage_state(db, system.system_id, live.context)
        return f"登录继续完成：{result.get('message', '')} 当前 URL: {result.get('url', live.page.url)}"

    if not result.get("success"):
        return f"登录失败：{result.get('error', '未知错误')}"

    return json.dumps(result, ensure_ascii=False)


async def wait_for_otp_ui(
    db: Session,
    *,
    screen_session_id: str,
    selector: str,
    submit_selector: str = "",
    prompt: str = "请输入短信验证码",
    vela_session_id: str = "",
    agent_id: str = "",
) -> Dict[str, Any]:
    """Agent 显式调用：暂停并等待用户输入 OTP。"""
    live = get_live_session(screen_session_id)
    row = db.query(ScreenSession).filter(
        ScreenSession.screen_session_id == screen_session_id
    ).first()
    if not live and row:
        system = _get_system(db, row.system_id)
        live = await _open_live_browser_session(
            db,
            screen_session_id=screen_session_id,
            system_id=row.system_id,
            system=system,
        )
    if not live or not live.page:
        return {"success": False, "error": f"浏览器会话不存在: {screen_session_id}"}

    preview = {
        "flow_kind": "otp_wait",
        "prompt": prompt,
        "selector": selector,
        "submit_selector": submit_selector,
        "url": live.page.url,
    }
    if live.last_screenshot:
        preview["screenshot_b64"] = _b64(live.last_screenshot)

    approval = create_hitl_for_login_otp(
        db,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id or (row.vela_session_id if row else ""),
        agent_id=agent_id or (row.agent_id if row else ""),
        prompt=prompt,
        preview_payload=preview,
        otp_action={
            "selector": selector,
            "submit_selector": submit_selector,
        },
    )
    return {
        "success": True,
        "hitl_pending": True,
        "approval_id": approval.approval_id,
        "otp_required": True,
        "message": prompt,
        "preview_payload": preview,
        "screen_session_id": screen_session_id,
    }


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
        live = await _open_live_browser_session(
            db,
            screen_session_id=screen_session_id,
            system_id=row.system_id,
            system=system,
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
                tool_name="cu_act",
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
    target_el = None
    if target_ref and live.elements:
        from services.screenpilot.layers.ground import find_element_by_ref

        el = find_element_by_ref(live.elements, target_ref)
        if el:
            target_el = el
            target_label = el.get("label") or ""

    # Login fields: resolve {{username}}/{{password}} or prefer system vault over chat plaintext.
    if action == "type" and row and row.system_id:
        from services.screenpilot.layers.credential import (
            load_credential_map,
            resolve_value_with_credentials,
        )

        _cred = load_credential_map(db, row.system_id)
        if _cred:
            _before = value
            value = resolve_value_with_credentials(
                value, _cred, target_el=target_el, target_label=target_label
            )

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
            tool_name="cu_act",
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
    # If a login-looking click had no effect, nudge agent toward the real submit button.
    if (
        action == "click"
        and result.get("success")
        and result.get("effect_ok") is False
    ):
        hint = build_login_form_hint(live.elements or [])
        if hint and hint.get("submit_refs"):
            result["warning"] = (
                (result.get("warning") or "")
                + " 点击未产生登录跳转：请改点 login_form.submit_refs / value=text=登录，"
                "不要点域名前缀或「用户登录」标题。"
            ).strip()
            result["login_form_hint"] = hint
            result["suggest_click"] = {"value": "text=登录", "refs": hint.get("submit_refs")}

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

    audit_value = value
    if action == "type":
        tgt = result.get("target") or {}
        if (tgt.get("input_type") or "").lower() == "password" or tgt.get("field_kind") == "password":
            audit_value = "***"
        elif value and len(str(value)) >= 6:
            audit_value = "***"

    write_audit(
        db,
        screen_session_id=screen_session_id,
        vela_session_id=vela_session_id or (row.vela_session_id if row else ""),
        agent_id=agent_id or (row.agent_id if row else ""),
        action=action,
        risk_tier=risk_tier,
        payload={"target_ref": target_ref, "value": audit_value},
        screenshot_png=live.last_screenshot or None,
        verification=result.get("verification"),
    )

    out = {
        "success": True,
        "risk_tier": risk_tier,
        "executed": bool(result.get("executed", True)),
        "effect_ok": result.get("effect_ok"),
        "verification": result.get("verification"),
        "warning": result.get("warning"),
        "click_mode": result.get("click_mode"),
        "observe": {
            "url": obs.get("url"),
            "elements": obs.get("elements"),
            "som_image_b64": obs.get("som_image_b64"),
            "login_form_hint": obs.get("login_form_hint"),
        },
    }
    if result.get("login_form_hint"):
        out["login_form_hint"] = result["login_form_hint"]
    if result.get("suggest_click"):
        out["suggest_click"] = result["suggest_click"]
    return out


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
        system = _get_system(db, skill.system_id)
        live = await _open_live_browser_session(
            db,
            screen_session_id=screen_session_id,
            system_id=row.system_id,
            system=system,
        )

    risk_rules = (system.risk_rules or {}) if system else {}
    from services.screenpilot.layers.credential import load_credential_map

    cred_map = load_credential_map(db, skill.system_id) if skill.system_id else {}
    incoming = dict(params or {})
    from services.screenpilot.layers.credential import merge_params_with_credentials

    params = merge_params_with_credentials(cred_map, incoming)
    results = []

    for step in steps:
        raw_tpl = step.value_template or ""
        value = resolve_template(raw_tpl, params)
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
                tool_name="cu_replay_skill",
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
                    "visibility": getattr(skill, "visibility", "PRIVATE") or "PRIVATE",
                    "status": skill.status or "ACTIVE",
                    "score": score,
                }
            )
    return {"success": True, "items": items}


async def execute_deferred_ui_act(db: Session, approval: HITLApproval) -> str:
    """HITL 批准后执行挂起的 cu_act / cu_replay_skill（兼容历史 ui_*）。"""
    args = approval.tool_args or {}
    if approval.tool_name in ("cu_replay_skill", "ui_replay_skill") and args.get("skill_id"):
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


async def _resolve_vision_model(db: Session):
    """Pick an active ModelService suitable for vision / multimodal chat."""
    from models import ModelProvider, ModelService, ModelServiceStatus, ProviderStatus
    from services.screenpilot.config import (
        SCREENPILOT_VISION_MODEL_NAME,
        SCREENPILOT_VISION_MODEL_SERVICE_ID,
    )

    svc = None
    if SCREENPILOT_VISION_MODEL_SERVICE_ID:
        svc = (
            db.query(ModelService)
            .filter(ModelService.model_service_id == SCREENPILOT_VISION_MODEL_SERVICE_ID)
            .first()
        )
    if not svc and SCREENPILOT_VISION_MODEL_NAME:
        svc = (
            db.query(ModelService)
            .filter(
                ModelService.model_name == SCREENPILOT_VISION_MODEL_NAME,
                ModelService.status == ModelServiceStatus.ACTIVE,
            )
            .first()
        )
    if not svc:
        candidates = (
            db.query(ModelService)
            .filter(ModelService.status == ModelServiceStatus.ACTIVE)
            .all()
        )
        for row in candidates:
            caps = row.capabilities or []
            name = (row.model_name or "").lower()
            if "vision" in caps or "image" in caps or "vl" in name or "vision" in name or "gpt-4o" in name:
                svc = row
                break
        if not svc and candidates:
            # Last resort: try first active service; provider may reject if not multimodal.
            svc = candidates[0]
    if not svc:
        return None, None, "未配置可用模型服务（设置 SCREENPILOT_VISION_MODEL_SERVICE_ID）"
    provider = (
        db.query(ModelProvider)
        .filter(
            ModelProvider.provider_id == svc.provider_id,
            ModelProvider.status == ProviderStatus.ACTIVE,
        )
        .first()
    )
    if not provider or not (provider.api_key or "").strip():
        return None, None, "视觉模型对应的 Provider 未配置或缺少 API Key"
    return provider, svc, ""


async def vision_query(
    db: Session,
    *,
    screen_session_id: str,
    question: str,
    use_som: bool = False,
) -> Dict[str, Any]:
    """Ask a multimodal model about the current page screenshot (Hermes browser_vision style)."""
    live = get_live_session(screen_session_id)
    if not live:
        return {"success": False, "error": f"浏览器会话不存在: {screen_session_id}", "vision_unavailable": False}

    q = (question or "").strip()
    if not q:
        return {"success": False, "error": "question 不能为空"}

    shot = live.last_som_image if use_som and live.last_som_image else live.last_screenshot
    if not shot and live.page:
        try:
            shot = await live.page.screenshot(type="png", full_page=False)
            live.last_screenshot = shot
        except Exception as e:
            return {"success": False, "error": f"截图失败: {e}"}
    if not shot:
        return {"success": False, "error": "无可用截图，请先 cu_observe"}

    provider, svc, err = await _resolve_vision_model(db)
    if err or not provider or not svc:
        return {
            "success": False,
            "vision_unavailable": True,
            "error": err or "vision_unavailable",
        }

    from services.model_provider import model_provider_service

    b64 = _b64(shot)
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "你是企业内系统界面助手。根据截图简洁回答问题；"
                        "如需指出可点击控件，尽量描述可见文案与大致位置。"
                        f"\n\n问题：{q}"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ],
        }
    ]
    try:
        completion = await model_provider_service.chat_completion(
            provider,
            svc.model_name,
            messages,  # multimodal payload
            max_tokens=min(int(svc.max_tokens or 1024), 2048),
            temperature=0.2,
        )
    except Exception as e:
        msg = str(e)
        unavailable = any(
            x in msg.lower()
            for x in ("vision", "image", "multimodal", "unsupported", "invalid", "400")
        )
        return {
            "success": False,
            "vision_unavailable": unavailable,
            "error": f"视觉模型调用失败: {msg[:400]}",
            "model_name": svc.model_name,
        }

    answer = ""
    choices = completion.get("choices") or []
    if choices:
        answer = ((choices[0].get("message") or {}).get("content") or "").strip()

    write_audit(
        db,
        screen_session_id=screen_session_id,
        vela_session_id="",
        agent_id="",
        action="vision",
        risk_tier="T0",
        screenshot_png=shot,
        payload={"question": q[:200], "model": svc.model_name, "answer_len": len(answer)},
    )
    return {
        "success": True,
        "screen_session_id": screen_session_id,
        "answer": answer,
        "model_name": svc.model_name,
        "used_som": bool(use_som and live.last_som_image),
    }


TOOL_HANDLERS = {
    "cu_navigate": navigate_ui,
    "cu_observe": lambda db, **kw: observe_session(db, kw["screen_session_id"]),
    "cu_act": act_ui,
    "cu_extract": lambda db, **kw: extract_ui(db, kw["screen_session_id"]),
    "cu_replay_skill": replay_skill,
    "cu_compile_skill": compile_skill,
    "cu_search_skills": search_skills,
    "cu_wait_for_otp": wait_for_otp_ui,
    "cu_vision": vision_query,
}
