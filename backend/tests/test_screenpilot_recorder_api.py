"""UI skill recorder: step notes, trajectory CRUD, skills/run API contract."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from database import SessionLocal, init_db
from models import ScreenSession, ScreenSystem, UiSkillStep, gen_uuid, now_utc
from routes import screenpilot as sp_routes
from services.screenpilot.trajectory import (
    append_trajectory_step,
    clear_trajectory,
    compile_trajectory_to_skill,
    fill_missing_skill_params,
    format_step_note,
    get_trajectory,
    replace_trajectory,
    resolve_template,
)


class TestFormatStepNote:
    def test_click_with_label(self):
        assert format_step_note("click", "通讯录") == "点击「通讯录」"

    def test_click_without_label(self):
        assert format_step_note("click", "") == "点击目标元素"

    def test_type_with_label_and_value(self):
        note = format_step_note("type", "搜索框", "张三")
        assert "搜索框" in note
        assert "张三" in note

    def test_type_label_only(self):
        assert format_step_note("type", "搜索框") == "在「搜索框」输入内容"

    def test_select(self):
        assert "选择" in format_step_note("select", "部门", "研发")

    def test_navigate(self):
        assert "导航" in format_step_note("navigate", "", "https://example.com")

    def test_press(self):
        assert "Enter" in format_step_note("press", "", "Enter")


class TestFillMissingSkillParams:
    def test_fills_query_from_goal(self):
        steps = [{"value_template": "{{query}}", "action": "type"}]
        out = fill_missing_skill_params({}, steps, goal="搜索harness相关论文")
        assert out["query"] == "harness"
        assert resolve_template("{{query}}", out) == "harness"

    def test_keeps_explicit_query(self):
        steps = [{"value_template": "{{query}}"}]
        out = fill_missing_skill_params({"query": "harness"}, steps, goal="搜索harness相关论文")
        assert out["query"] == "harness"

    def test_does_not_fill_password_from_goal(self):
        steps = [{"value_template": "{{password}}"}]
        out = fill_missing_skill_params({}, steps, goal="搜索harness")
        assert "password" not in out or not out.get("password")

    def test_extract_search_query_hint(self):
        from services.screenpilot.trajectory import extract_search_query_hint

        assert extract_search_query_hint("使用驭屏系统 在arxiv上搜索harness相关论文。") == "harness"
        assert extract_search_query_hint('搜索「LLM agent」') == "LLM agent"


class TestMultiParamSchemaAndExtract:
    def test_sanitize_param_key(self):
        from services.screenpilot.trajectory import sanitize_trajectory_value, suggest_param_key

        assert suggest_param_key("搜索框") == "query"
        assert suggest_param_key("部门") == "dept"
        assert (
            sanitize_trajectory_value(
                {"action": "type", "param_key": "query", "value": "harness"}
            )
            == "{{query}}"
        )

    def test_infer_param_schema_descriptions(self):
        from services.screenpilot.trajectory import infer_param_schema

        schema = infer_param_schema(
            [
                {"value_template": "{{query}}", "target_label": "搜索"},
                {
                    "value_template": "{{dept}}",
                    "target_label": "部门",
                    "note": "选择目标部门",
                },
            ]
        )
        assert schema["properties"]["query"]["description"]
        assert schema["properties"]["dept"]["description"] == "选择目标部门"
        assert set(schema["required"]) == {"query", "dept"}

    def test_rule_extraction_multi(self):
        from services.screenpilot.param_extract import apply_rule_extraction

        out = apply_rule_extraction(
            "搜索harness相关论文，dept:研发",
            ["query", "dept"],
            {},
        )
        assert out.get("query") == "harness"
        assert out.get("dept") == "研发"

    def test_rule_extraction_title_text_chinese(self):
        from services.screenpilot.param_extract import apply_rule_extraction

        text = (
            '使用驭屏系统，发布小红书帖文。'
            '标题：“我的测试贴”，正文：“这是一个使用agent发布的测试贴文”'
        )
        out = apply_rule_extraction(text, ["title", "text"], {})
        assert out.get("title") == "我的测试贴"
        assert out.get("text") == "这是一个使用agent发布的测试贴文"

    @pytest.mark.asyncio
    async def test_extract_without_llm_reports_missing(self):
        from services.screenpilot.param_extract import extract_skill_params

        res = await extract_skill_params(
            None,
            user_text="打开通讯录",
            param_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词"},
                    "dept": {"type": "string", "description": "部门"},
                },
                "required": ["query", "dept"],
            },
            existing={},
            use_llm=False,
        )
        assert "query" in res["missing"]
        assert "dept" in res["missing"]


class TestCompileParamKey:
    def setup_method(self):
        init_db()
        self.db = SessionLocal()
        self.system = ScreenSystem(
            system_id=gen_uuid(),
            name=f"sys_{gen_uuid()[:8]}",
            entry_url="https://example.com",
            allowed_domains=["example.com"],
            status="ACTIVE",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(self.system)
        self.db.flush()
        self.session = ScreenSession(
            screen_session_id=gen_uuid(),
            system_id=self.system.system_id,
            status="ACTIVE",
            meta={},
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(self.session)
        self.db.commit()

    def teardown_method(self):
        try:
            self.db.rollback()
            self.db.close()
        except Exception:
            pass

    def test_compile_writes_placeholders(self):
        append_trajectory_step(
            self.db,
            self.session.screen_session_id,
            {
                "action": "type",
                "target_label": "搜索",
                "value": "harness",
                "param_key": "query",
            },
        )
        append_trajectory_step(
            self.db,
            self.session.screen_session_id,
            {
                "action": "select",
                "target_label": "部门",
                "value": "研发",
                "param_key": "dept",
            },
        )
        compiled = compile_trajectory_to_skill(
            self.db,
            screen_session_id=self.session.screen_session_id,
            name=f"skill_{gen_uuid()[:8]}",
            description="multi param",
            scope="default",
        )
        assert compiled.get("success")
        steps = (
            self.db.query(UiSkillStep)
            .filter(UiSkillStep.skill_id == compiled["skill_id"])
            .order_by(UiSkillStep.step_order)
            .all()
        )
        templates = [s.value_template for s in steps]
        assert "{{query}}" in templates
        assert "{{dept}}" in templates
        schema = compiled.get("param_schema") or {}
        assert "query" in (schema.get("properties") or {})
        assert "dept" in (schema.get("properties") or {})


class TestReplayNeedsParamsHitl:
    def setup_method(self):
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        try:
            self.db.rollback()
            self.db.close()
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_missing_params_creates_hitl_when_session(self):
        from models import Agent, AgentStatus, AgentType, ModelProvider, ModelService, ProviderStatus, Session as AgentSession, UiSkill
        from services.screenpilot.service import replay_skill
        from services.screenpilot.skill_store import skill_store

        provider = ModelProvider(
            provider_code=f"p_{gen_uuid()[:6]}",
            display_name="p",
            base_url="https://example.com",
            api_key="x",
            status=ProviderStatus.ACTIVE,
        )
        self.db.add(provider)
        self.db.flush()
        model = ModelService(
            provider_id=provider.provider_id,
            model_name="m",
            display_name="m",
            status="ACTIVE",
        )
        self.db.add(model)
        self.db.flush()
        agent = Agent(
            agent_id=gen_uuid(),
            name=f"a_{gen_uuid()[:6]}",
            model_service_id=model.model_service_id,
            status=AgentStatus.PUBLISHED,
            agent_type=AgentType.SINGLE,
            system_prompt="x",
        )
        self.db.add(agent)
        self.db.flush()
        vela = AgentSession(
            session_id=gen_uuid(),
            agent_id=agent.agent_id,
            status="ACTIVE",
            messages=[],
        )
        self.db.add(vela)
        system = ScreenSystem(
            system_id=gen_uuid(),
            name=f"sys_{gen_uuid()[:8]}",
            entry_url="https://example.com",
            allowed_domains=["example.com"],
            status="ACTIVE",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(system)
        self.db.flush()
        screen = ScreenSession(
            screen_session_id=gen_uuid(),
            system_id=system.system_id,
            status="ACTIVE",
            meta={},
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(screen)
        self.db.flush()
        skill = skill_store.create_skill(
            self.db,
            name=f"sk_{gen_uuid()[:8]}",
            description="d",
            system_id=system.system_id,
            steps=[
                {
                    "action": "type",
                    "target_label": "搜索",
                    "value_template": "{{query}}",
                    "fingerprints": {},
                    "meta": {"note": "关键词"},
                },
                {
                    "action": "type",
                    "target_label": "部门",
                    "value_template": "{{dept}}",
                    "fingerprints": {},
                    "meta": {"note": "部门"},
                },
            ],
            scope="default",
            param_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词"},
                    "dept": {"type": "string", "description": "部门"},
                },
                "required": ["query", "dept"],
            },
        )
        self.db.commit()

        with patch(
            "services.screenpilot.service._ensure_replay_live_session",
            new_callable=AsyncMock,
            return_value=type("L", (), {"page": object(), "elements": [], "exec_mode": "browser"})(),
        ), patch(
            "services.screenpilot.param_extract.extract_skill_params",
            new_callable=AsyncMock,
            return_value={"values": {}, "missing": ["query", "dept"], "filled_keys": []},
        ):
            res = await replay_skill(
                self.db,
                skill_id=skill.skill_id,
                screen_session_id=screen.screen_session_id,
                params={},
                vela_session_id=vela.session_id,
                agent_id=agent.agent_id,
            )
        assert res.get("hitl_pending") is True
        assert res.get("needs_params") is True
        assert set(res.get("missing_params") or []) == {"query", "dept"}
        assert res.get("preview_payload", {}).get("flow_kind") == "skill_params"


class TestReplaySkillSkipsStepHitl:
    """T2/T3 labeled steps must auto-run during skill replay (no step HITL)."""

    def setup_method(self):
        init_db()
        self.db = SessionLocal()

    def teardown_method(self):
        try:
            self.db.rollback()
            self.db.close()
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_t2_step_runs_without_hitl_when_force_execute_false(self):
        from models import (
            Agent,
            AgentStatus,
            AgentType,
            ModelProvider,
            ModelService,
            ProviderStatus,
            Session as AgentSession,
        )
        from services.screenpilot.service import replay_skill
        from services.screenpilot.skill_store import skill_store

        provider = ModelProvider(
            provider_code=f"p_{gen_uuid()[:6]}",
            display_name="p",
            base_url="https://example.com",
            api_key="x",
            status=ProviderStatus.ACTIVE,
        )
        self.db.add(provider)
        self.db.flush()
        model = ModelService(
            provider_id=provider.provider_id,
            model_name="m",
            display_name="m",
            status="ACTIVE",
        )
        self.db.add(model)
        self.db.flush()
        agent = Agent(
            agent_id=gen_uuid(),
            name=f"a_{gen_uuid()[:6]}",
            model_service_id=model.model_service_id,
            status=AgentStatus.PUBLISHED,
            agent_type=AgentType.SINGLE,
            system_prompt="x",
        )
        self.db.add(agent)
        self.db.flush()
        vela = AgentSession(
            session_id=gen_uuid(),
            agent_id=agent.agent_id,
            status="ACTIVE",
            messages=[],
        )
        self.db.add(vela)
        system = ScreenSystem(
            system_id=gen_uuid(),
            name=f"sys_{gen_uuid()[:8]}",
            entry_url="https://example.com",
            allowed_domains=["example.com"],
            status="ACTIVE",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(system)
        self.db.flush()
        screen = ScreenSession(
            screen_session_id=gen_uuid(),
            system_id=system.system_id,
            status="ACTIVE",
            meta={},
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(screen)
        self.db.flush()
        skill = skill_store.create_skill(
            self.db,
            name=f"sk_{gen_uuid()[:8]}",
            description="d",
            system_id=system.system_id,
            steps=[
                {
                    "action": "click",
                    "target_label": "写长文",
                    "value_template": "",
                    "fingerprints": {"css": "button.write"},
                    "meta": {},
                },
                {
                    "action": "click",
                    "target_label": "暂存离开",
                    "value_template": "",
                    "fingerprints": {"css": "button.save"},
                    "meta": {},
                },
            ],
            scope="default",
            param_schema={"type": "object", "properties": {}, "required": []},
        )
        self.db.commit()

        live = type(
            "L",
            (),
            {
                "page": object(),
                "elements": [],
                "exec_mode": "browser",
                "context": None,
            },
        )()
        exec_ok = {
            "success": True,
            "locate_method": "css",
            "verification": {"ok": True},
        }

        with patch(
            "services.screenpilot.service._ensure_replay_live_session",
            new_callable=AsyncMock,
            return_value=live,
        ), patch(
            "services.screenpilot.service.execute_by_fingerprints",
            new_callable=AsyncMock,
            return_value=exec_ok,
        ), patch(
            "services.screenpilot.service.observe_session",
            new_callable=AsyncMock,
            return_value={"success": True, "url": "https://example.com"},
        ), patch(
            "services.screenpilot.service.write_audit",
            return_value=None,
        ):
            res = await replay_skill(
                self.db,
                skill_id=skill.skill_id,
                screen_session_id=screen.screen_session_id,
                params={},
                vela_session_id=vela.session_id,
                agent_id=agent.agent_id,
                force_execute=False,
            )

        assert res.get("hitl_pending") is not True
        assert res.get("success") is True
        assert res.get("replayed_steps") == 2
        tiers = [r.get("risk_tier") for r in (res.get("results") or [])]
        assert "T2" in tiers


class TestTrajectoryNoteAndCompile:
    def setup_method(self):
        init_db()
        self.db = SessionLocal()
        self.system = ScreenSystem(
            system_id=gen_uuid(),
            name=f"sys_{gen_uuid()[:8]}",
            entry_url="https://example.com",
            allowed_domains=["example.com"],
            status="ACTIVE",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(self.system)
        self.db.flush()
        self.session = ScreenSession(
            screen_session_id=gen_uuid(),
            system_id=self.system.system_id,
            status="ACTIVE",
            meta={},
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(self.session)
        self.db.commit()

    def teardown_method(self):
        try:
            self.db.close()
        except Exception:
            pass

    def test_append_auto_note(self):
        append_trajectory_step(
            self.db,
            self.session.screen_session_id,
            {"action": "click", "target_label": "通讯录", "value": None},
        )
        steps = get_trajectory(self.db, self.session.screen_session_id)
        assert len(steps) == 1
        assert steps[0]["note"] == "点击「通讯录」"

    def test_append_custom_note_preserved(self):
        append_trajectory_step(
            self.db,
            self.session.screen_session_id,
            {
                "action": "click",
                "target_label": "通讯录",
                "note": "打开通讯录入口",
            },
        )
        steps = get_trajectory(self.db, self.session.screen_session_id)
        assert steps[0]["note"] == "打开通讯录入口"

    def test_replace_and_clear(self):
        replace_trajectory(
            self.db,
            self.session.screen_session_id,
            [
                {"action": "click", "target_label": "A", "note": "第一步"},
                {"action": "type", "target_label": "搜索", "value": "x"},
            ],
        )
        steps = get_trajectory(self.db, self.session.screen_session_id)
        assert len(steps) == 2
        assert steps[0]["step_order"] == 1
        assert steps[1]["note"]  # auto-generated
        clear_trajectory(self.db, self.session.screen_session_id)
        assert get_trajectory(self.db, self.session.screen_session_id) == []

    def test_compile_preserves_note_in_meta(self):
        append_trajectory_step(
            self.db,
            self.session.screen_session_id,
            {
                "action": "click",
                "target_label": "通讯录",
                "note": "点击通讯录菜单",
                "fingerprints": {"label": "通讯录"},
            },
        )
        with patch(
            "services.screenpilot.trajectory.skill_store.index_skill",
            return_value=None,
        ):
            result = compile_trajectory_to_skill(
                self.db,
                screen_session_id=self.session.screen_session_id,
                name="测试通讯录技能",
                description="打开通讯录",
                scope="default",
            )
        assert result.get("success") is True
        skill_id = result["skill_id"]
        steps = (
            self.db.query(UiSkillStep)
            .filter(UiSkillStep.skill_id == skill_id)
            .order_by(UiSkillStep.step_order)
            .all()
        )
        assert len(steps) >= 1
        meta = steps[0].meta or {}
        assert meta.get("note") == "点击通讯录菜单"


class TestTrajectoryRestHandlers:
    def setup_method(self):
        init_db()
        self.db = SessionLocal()
        self.system = ScreenSystem(
            system_id=gen_uuid(),
            name=f"sys_{gen_uuid()[:8]}",
            entry_url="https://example.com",
            allowed_domains=["example.com"],
            status="ACTIVE",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(self.system)
        self.db.flush()
        self.session = ScreenSession(
            screen_session_id=gen_uuid(),
            system_id=self.system.system_id,
            status="ACTIVE",
            meta={"trajectory": [{"action": "click", "target_label": "X", "note": "n1", "step_order": 1}]},
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.db.add(self.session)
        self.db.commit()

    def teardown_method(self):
        try:
            self.db.query(ScreenSession).filter(
                ScreenSession.screen_session_id == self.session.screen_session_id
            ).delete()
            self.db.query(ScreenSystem).filter(
                ScreenSystem.system_id == self.system.system_id
            ).delete()
            self.db.commit()
        finally:
            self.db.close()

    def test_get_trajectory_api(self):
        with patch.object(sp_routes, "is_screenpilot_enabled", return_value=True):
            res = sp_routes.get_trajectory_api(self.session.screen_session_id, self.db)
        assert res["success"] is True
        assert res["step_count"] == 1
        assert res["steps"][0]["note"] == "n1"

    def test_get_trajectory_404(self):
        with patch.object(sp_routes, "is_screenpilot_enabled", return_value=True):
            with pytest.raises(HTTPException) as ei:
                sp_routes.get_trajectory_api("missing-session", self.db)
        assert ei.value.status_code == 404

    def test_clear_trajectory_api(self):
        with patch.object(sp_routes, "is_screenpilot_enabled", return_value=True):
            res = sp_routes.clear_trajectory_api(self.session.screen_session_id, self.db)
        assert res["success"] is True
        assert res["step_count"] == 0

    def test_replace_trajectory_api(self):
        body = sp_routes.TrajectoryReplaceRequest(
            steps=[{"action": "type", "target_label": "搜索框", "value": "abc"}]
        )
        with patch.object(sp_routes, "is_screenpilot_enabled", return_value=True):
            res = sp_routes.replace_trajectory_api(
                self.session.screen_session_id, body, self.db
            )
        assert res["step_count"] == 1
        assert "搜索框" in (res["steps"][0].get("note") or "")


@pytest.mark.asyncio
async def test_skills_run_api_calls_run_task():
    body = sp_routes.SkillRunRequest(
        system_id="sys-1",
        goal="打开通讯录",
        scope="default",
    )
    mock_result = {"success": True, "task_trace": [{"phase": "plan"}]}
    with patch.object(sp_routes, "is_screenpilot_enabled", return_value=True):
        with patch(
            "services.screenpilot.run_task.run_task",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mocked:
            res = await sp_routes.run_skill_api(body, db=None)
    assert res["success"] is True
    mocked.assert_awaited_once()
    kwargs = mocked.await_args.kwargs
    assert kwargs["system_id"] == "sys-1"
    assert kwargs["goal"] == "打开通讯录"
