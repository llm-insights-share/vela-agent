"""Tests for resolve_effective_model modality routing."""
from __future__ import annotations

from types import SimpleNamespace

from services.agent_service import resolve_effective_model


def _svc(model_name: str, capabilities: list[str] | None = None):
    return SimpleNamespace(
        model_name=model_name,
        capabilities=list(capabilities or ["text"]),
        model_service_id=f"ms-{model_name}",
    )


def _provider(code: str = "p"):
    return SimpleNamespace(provider_id=f"prov-{code}", provider_code=code)


def test_no_vision_required_uses_primary():
    primary_p, primary_m = _provider("primary"), _svc("deepseek-chat", ["text"])
    aux_p, aux_m = _provider("aux"), _svc("qwen-vl", ["text", "vision"])
    p, m, reason = resolve_effective_model(
        primary_p, primary_m, aux_p, aux_m, required_modalities=["text"]
    )
    assert reason == "primary"
    assert m is primary_m
    assert p is primary_p


def test_empty_modalities_uses_primary():
    primary_p, primary_m = _provider("primary"), _svc("deepseek-chat", ["text"])
    p, m, reason = resolve_effective_model(primary_p, primary_m, required_modalities=None)
    assert reason == "primary"
    assert m is primary_m


def test_vision_primary_supports_stays_primary():
    primary_p, primary_m = _provider("primary"), _svc("gpt-4o", ["text", "vision"])
    aux_p, aux_m = _provider("aux"), _svc("qwen-vl", ["text", "vision"])
    p, m, reason = resolve_effective_model(
        primary_p, primary_m, aux_p, aux_m, required_modalities=["text", "vision"]
    )
    assert reason == "primary"
    assert m is primary_m


def test_vision_primary_lacks_aux_supports_switches_to_aux():
    primary_p, primary_m = _provider("primary"), _svc("deepseek-chat", ["text"])
    aux_p, aux_m = _provider("aux"), _svc("qwen-vl-plus", ["text", "vision"])
    p, m, reason = resolve_effective_model(
        primary_p, primary_m, aux_p, aux_m, required_modalities=["vision"]
    )
    assert reason == "aux"
    assert m is aux_m
    assert p is aux_p


def test_vision_primary_lacks_aux_missing_falls_back_ocr_path():
    primary_p, primary_m = _provider("primary"), _svc("deepseek-chat", ["text"])
    p, m, reason = resolve_effective_model(
        primary_p, primary_m, None, None, required_modalities=["vision"]
    )
    assert reason == "primary_ocr_fallback"
    assert m is primary_m


def test_vision_primary_lacks_aux_also_text_only_falls_back():
    primary_p, primary_m = _provider("primary"), _svc("deepseek-chat", ["text"])
    aux_p, aux_m = _provider("aux"), _svc("deepseek-reasoner", ["text"])
    p, m, reason = resolve_effective_model(
        primary_p, primary_m, aux_p, aux_m, required_modalities=["image"]
    )
    assert reason == "primary_ocr_fallback"
    assert m is primary_m


def test_vision_inferred_from_model_name_on_aux():
    primary_p, primary_m = _provider("primary"), _svc("deepseek-chat", ["text"])
    # capabilities omit vision but name looks like VL
    aux_p, aux_m = _provider("aux"), _svc("qwen2.5-vl-72b", ["text"])
    p, m, reason = resolve_effective_model(
        primary_p, primary_m, aux_p, aux_m, required_modalities=["vision"]
    )
    assert reason == "aux"
    assert m is aux_m
