"""ScreenPilot selective-absorb: URL safety, navigation, goal verify, session touch."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from services.screenpilot.layers.govern import check_domain_allowed, check_navigation_allowed
from services.screenpilot.run_task import verify_goal, _parse_goal_rules
from services.screenpilot.url_safety import (
    check_url_safety,
    host_in_allowlist,
    url_contains_secret,
)


class TestUrlSafety:
    def test_blocks_metadata_hostname(self):
        ok, reason = check_url_safety("http://metadata.google.internal/latest")
        assert ok is False
        assert "metadata" in reason.lower() or "拦截" in reason

    def test_blocks_link_local_metadata_ip(self):
        ok, reason = check_url_safety("http://169.254.169.254/latest/meta-data/")
        assert ok is False

    def test_blocks_private_without_allowlist(self):
        ok, reason = check_url_safety("http://10.0.0.8/oa")
        assert ok is False
        assert "白名单" in reason or "私网" in reason

    def test_allows_private_when_allowlisted(self):
        ok, reason = check_url_safety(
            "http://10.0.0.8/oa",
            allowed_domains=["10.0.0.8"],
        )
        assert ok is True, reason

    def test_blocks_non_http_scheme(self):
        ok, reason = check_url_safety("file:///etc/passwd")
        assert ok is False
        assert "http" in reason.lower() or "scheme" in reason.lower()

    def test_secret_in_url(self):
        assert url_contains_secret("https://evil.com/x?key=sk-ant-abcdefghijklmnopqrstuvwxyz")
        ok, reason = check_url_safety(
            "https://evil.com/steal?token=sk-abcdefghijklmnopqrstuvwxyz0123"
        )
        assert ok is False
        assert "密钥" in reason or "令牌" in reason

    def test_host_in_allowlist_subdomain(self):
        assert host_in_allowlist("a.oa.corp.com", ["oa.corp.com"]) is True
        assert host_in_allowlist("evil.com", ["oa.corp.com"]) is False


class TestGovernNavigation:
    def test_domain_allowlist_required(self):
        assert check_domain_allowed("https://a.example.com/x", ["example.com"]) is True
        assert check_domain_allowed("https://other.com/x", ["example.com"]) is False

    def test_navigation_combines_domain_and_safety(self):
        ok, reason = check_navigation_allowed(
            "http://169.254.169.254/",
            ["169.254.169.254"],
        )
        # metadata always blocked even if somehow allowlisted via IP check in safety
        assert ok is False

    def test_navigation_public_ok_empty_allowlist(self):
        with patch(
            "services.screenpilot.url_safety.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
        ):
            ok, reason = check_navigation_allowed("https://example.com/path", [])
            assert ok is True, reason

    def test_navigation_rejects_off_allowlist(self):
        ok, reason = check_navigation_allowed(
            "https://evil.com/",
            ["oa.internal"],
        )
        assert ok is False
        assert "白名单" in reason


class TestGoalVerify:
    def test_parse_rules(self):
        text, rules = _parse_goal_rules("打开列表 url_contains=/orders title_contains=订单")
        assert rules["url_contains"] == "/orders"
        assert rules["title_contains"] == "订单"
        assert "打开列表" in text

    def test_url_contains_met(self):
        r = verify_goal(
            "完成登录 url_contains=/home",
            page_text="",
            url="https://oa/home?x=1",
            title="",
        )
        assert r["met"] is True
        assert r["via"] == "url_contains"

    def test_text_keywords_met(self):
        r = verify_goal(
            "查看审批通过",
            page_text="你的申请已审批通过，谢谢",
            url="https://oa/x",
        )
        assert r["met"] is True

    def test_login_wall_not_success(self):
        r = verify_goal(
            "进入工作台",
            page_text="请登录后继续",
            url="https://oa/login",
            observe={"login_required": True},
        )
        # keywords may or may not match; with login_required and weak match should fail if keywords don't cover
        # "进入工作台" bigrams unlikely in login text → unmet
        assert r["met"] is False


class TestSessionActivity:
    def test_touch_updates_activity(self):
        from services.screenpilot import session_manager as sm

        sid = "test-session-touch"
        # inject a fake session
        sess = sm.LiveSession(
            screen_session_id=sid,
            system_id="sys",
            context=None,
            page=None,
            exec_mode="desktop",
            last_activity_at=time.monotonic() - 999,
        )
        sm._sessions[sid] = sess
        try:
            before = sess.last_activity_at
            got = sm.get_live_session(sid)
            assert got is sess
            assert sess.last_activity_at >= before
            sm.touch_session(sid)
            assert sess.last_activity_at >= before
        finally:
            sm._sessions.pop(sid, None)
