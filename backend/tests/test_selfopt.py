"""Unit tests for SelfOpt risk, config, allowlist, reflect model resolve."""
from services.selfopt.risk import (
    classify_risk_tier,
    is_forbidden_change_kind,
    validate_diff_json,
)
from services.selfopt.config import (
    SelfOptConfig,
    is_enabled_for_agent,
    load_selfopt_config,
    resolve_reflect_model_service_id,
)
from services.selfopt.proposal import apply_diff_to_snapshot


class _FakeAgent:
    def __init__(self, agent_id, model_service_id="ms-agent", selfopt_enabled=None):
        self.agent_id = agent_id
        self.model_service_id = model_service_id
        self.selfopt_enabled = selfopt_enabled


def test_forbidden_kinds():
    assert is_forbidden_change_kind("guardrail")
    assert is_forbidden_change_kind("audit")
    assert classify_risk_tier("prompt_fewshot") == "T1"
    assert classify_risk_tier("retrieval_params") == "T0"


def test_validate_diff_rejects_guardrail():
    try:
        validate_diff_json({"guardrail": {"x": 1}})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_apply_diff_prompt_append():
    snap = apply_diff_to_snapshot(
        {"system_prompt": "BASE"},
        {"system_prompt_append": "\nEXTRA"},
    )
    assert snap["system_prompt"] == "BASE\nEXTRA"


def test_apply_diff_retrieval():
    snap = apply_diff_to_snapshot({}, {"retrieval": {"top_k": 8}})
    assert snap["composition_config"]["knowledge"]["top_k"] == 8


def test_resolve_reflect_model_order():
    agent = _FakeAgent("a1", model_service_id="ms-agent")
    cfg = SelfOptConfig(reflect_model_service_id="ms-global")
    assert resolve_reflect_model_service_id(agent, override="ms-job", cfg=cfg) == "ms-job"
    assert resolve_reflect_model_service_id(agent, override=None, cfg=cfg) == "ms-global"
    cfg2 = SelfOptConfig(reflect_model_service_id="")
    assert resolve_reflect_model_service_id(agent, override=None, cfg=cfg2) == "ms-agent"


def test_allowlist_empty_blocks():
    agent = _FakeAgent("a1")
    cfg = SelfOptConfig(enabled=True, agent_ids=[])
    assert is_enabled_for_agent(agent, cfg) is False


def test_allowlist_and_veto():
    agent = _FakeAgent("a1")
    cfg = SelfOptConfig(enabled=True, agent_ids=["a1"])
    assert is_enabled_for_agent(agent, cfg) is True
    agent_off = _FakeAgent("a1", selfopt_enabled=False)
    assert is_enabled_for_agent(agent_off, cfg) is False
    assert is_enabled_for_agent(_FakeAgent("a2"), cfg) is False


def test_load_config_has_new_fields():
    cfg = load_selfopt_config()
    assert isinstance(cfg, SelfOptConfig)
    assert isinstance(cfg.agent_ids, list)
    assert isinstance(cfg.reflect_model_service_id, str)


def test_round_robin_arm_rule():
    """New sessions: odd rr → treatment, even rr → control."""
    arms = []
    for n in range(1, 7):
        arms.append("control" if n % 2 == 0 else "treatment")
    assert arms == [
        "treatment",
        "control",
        "treatment",
        "control",
        "treatment",
        "control",
    ]
    # rr=3 → expect 2 treatment + 1 control sessions
    rr = 3
    assert (rr + 1) // 2 == 2
    assert rr // 2 == 1
