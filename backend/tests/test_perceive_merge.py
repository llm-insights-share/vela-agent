"""Unit tests for SoM perception merge / rank / risk_rules / effect helpers."""
from services.screenpilot.layers.govern import _target_state_changed
from services.screenpilot.layers.perceive import (
    box_iou,
    detect_risk_block,
    merge_elements,
    prepare_som_elements,
    rank_elements_for_som,
)


def _el(role, label, x, y, w=20, h=20, source="dom", checked=None):
    item = {
        "role": role,
        "label": label,
        "box": {"x": x, "y": y, "width": w, "height": h},
        "path": f"{source}/{role}",
        "source": source,
    }
    if checked is not None:
        item["checked"] = checked
    return item


def test_box_iou_overlap():
    a = {"x": 0, "y": 0, "width": 100, "height": 100}
    b = {"x": 50, "y": 50, "width": 100, "height": 100}
    assert 0.1 < box_iou(a, b) < 0.5
    assert box_iou(a, a) == 1.0


def test_merge_prefers_checkbox_over_generic():
    a11y = [_el("generic", "", 10, 10, source="a11y")]
    dom = [_el("checkbox", "我已阅读并同意《用户协议》", 12, 12, source="dom", checked=False)]
    merged = merge_elements(a11y, dom)
    assert len(merged) == 1
    assert merged[0]["role"] == "checkbox"
    assert "我已阅读" in merged[0]["label"]
    assert merged[0]["checked"] is False


def test_merge_keeps_distinct_elements():
    a11y = [_el("button", "登录", 100, 200, w=80, h=40, source="a11y")]
    dom = [_el("checkbox", "我已阅读并同意", 100, 260, w=16, h=16, source="dom")]
    merged = merge_elements(a11y, dom)
    assert len(merged) == 2


def test_rank_dialog_and_agreement_first():
    dialogs = [{"x": 200, "y": 100, "width": 400, "height": 500}]
    elements = [
        _el("link", "笔记卡片", 20, 20, w=200, h=200, source="a11y"),
        _el("checkbox", "我已阅读并同意《用户协议》", 250, 400, w=16, h=16, source="dom"),
        _el("button", "登录", 280, 350, w=120, h=40, source="dom"),
    ]
    ranked = rank_elements_for_som(elements, dialogs)
    assert ranked[0]["role"] == "checkbox"
    assert "我已阅读" in ranked[0]["label"]


def test_prepare_som_truncation_meta():
    a11y = [_el("button", f"b{i}", i * 30, 10, source="a11y") for i in range(5)]
    dom = [
        _el("checkbox", "我已阅读并同意", 50, 50, source="dom", checked=False),
        *[_el("link", f"l{i}", i * 30, 80, source="dom") for i in range(10)],
    ]
    capped, meta = prepare_som_elements(a11y, dom, dialogs=None, max_elements=8)
    assert len(capped) == 8
    assert meta["truncated"] is True
    assert meta["total_elements"] > 8
    assert meta["som_source"] == "a11y+dom"
    assert any(e["role"] == "checkbox" for e in capped)


def test_detect_risk_block_requires_config():
    assert detect_risk_block("ip存在风险", "https://example.com/err") is None
    rules = {
        "block_url_substrings": ["website-login/error"],
        "block_body_hints": ["ip存在风险"],
        "block_error_code": "300012",
        "block_message": "网络风险拦截",
    }
    hit_url = detect_risk_block("ok", "https://x.com/website-login/error?x=1", risk_rules=rules)
    assert hit_url and hit_url["error_code"] == "300012"
    hit_body = detect_risk_block("当前IP存在风险请切换", "https://x.com/", risk_rules=rules)
    assert hit_body and "风险" in hit_body["message"]


def test_target_state_changed_detects_checked_and_text():
    before = {"dom": {"text": "获取", "checked": False, "ariaChecked": "false", "disabled": False, "className": "a"}}
    after = {"dom": {"text": "60s", "checked": False, "ariaChecked": "false", "disabled": True, "className": "a"}}
    assert _target_state_changed(before, after) is True
    assert _target_state_changed(before, before) is False
    toggled = {"dom": {**before["dom"], "checked": True, "ariaChecked": "true"}}
    assert _target_state_changed(before, toggled) is True


def test_merge_keeps_adjacent_button_and_textbox():
    """Structural: phone textbox and nearby short-text button must remain distinct."""
    phone = _el("textbox", "手机号", 100, 100, w=160, h=36, source="dom")
    send = _el("button", "获取验证码", 280, 104, w=80, h=28, source="dom")
    merged = merge_elements([], [phone, send])
    assert len(merged) == 2
    roles = {e["role"] for e in merged}
    assert "textbox" in roles and "button" in roles


if __name__ == "__main__":
    test_box_iou_overlap()
    test_merge_prefers_checkbox_over_generic()
    test_merge_keeps_distinct_elements()
    test_rank_dialog_and_agreement_first()
    test_prepare_som_truncation_meta()
    test_detect_risk_block_requires_config()
    test_target_state_changed_detects_checked_and_text()
    test_merge_keeps_adjacent_button_and_textbox()
    print("all ok")
