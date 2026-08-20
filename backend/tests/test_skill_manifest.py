"""Tests for Skill manifest update API and merge logic."""
from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from database import SessionLocal, init_db
from models import SkillPack, gen_uuid
from routes.skills import _deep_merge_dict, update_skill
from schemas import SkillManifestSchema, SkillPackUpdate


def test_deep_merge_preserves_references():
    base = {"references": ["skill-a"], "trigger_keywords": ["old"]}
    overlay = {"trigger_keywords": ["开盘走势"]}
    merged = _deep_merge_dict(base, overlay)
    assert merged["references"] == ["skill-a"]
    assert merged["trigger_keywords"] == ["开盘走势"]


def test_deep_merge_nested_tool_budget():
    base = {"tool_budget": {"max_web_search": 5, "max_tool_rounds": 3}}
    overlay = {"tool_budget": {"max_web_search": 2}}
    merged = _deep_merge_dict(base, overlay)
    assert merged["tool_budget"]["max_web_search"] == 2
    assert merged["tool_budget"]["max_tool_rounds"] == 3


def test_skill_manifest_schema_rejects_invalid_budget():
    with pytest.raises(ValidationError):
        SkillManifestSchema.model_validate({
            "tool_budget": {"max_web_search": -1},
        })


def test_skill_manifest_schema_extra_fields():
    validated = SkillManifestSchema.model_validate({
        "trigger_keywords": ["688322"],
        "references": ["other-skill"],
    })
    dumped = validated.model_dump()
    assert dumped["trigger_keywords"] == ["688322"]
    assert dumped["references"] == ["other-skill"]


def test_update_skill_manifest_merge_and_sync_description():
    init_db()
    db = SessionLocal()
    name = f"manifest_test_{time.time()}"
    skill = SkillPack(
        skill_pack_id=gen_uuid(),
        name=name,
        description="old desc",
        manifest={"references": ["ref-1"], "version": "1.0.0"},
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)

    try:
        updated = update_skill(
            skill.skill_pack_id,
            SkillPackUpdate(
                manifest={
                    "trigger_keywords": ["开盘走势"],
                    "tool_budget": {"max_web_search": 4},
                    "description": "new desc from manifest",
                    "version": "2.0.0",
                }
            ),
            db,
        )
        assert updated.manifest["references"] == ["ref-1"]
        assert updated.manifest["trigger_keywords"] == ["开盘走势"]
        assert updated.manifest["tool_budget"]["max_web_search"] == 4
        assert updated.description == "new desc from manifest"
        assert updated.version == "2.0.0"
    finally:
        db.query(SkillPack).filter(SkillPack.skill_pack_id == skill.skill_pack_id).delete()
        db.commit()
        db.close()


def test_update_skill_invalid_manifest_returns_422():
    init_db()
    db = SessionLocal()
    name = f"manifest_bad_{time.time()}"
    skill = SkillPack(skill_pack_id=gen_uuid(), name=name, manifest={})
    db.add(skill)
    db.commit()
    db.refresh(skill)

    try:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            update_skill(
                skill.skill_pack_id,
                SkillPackUpdate(manifest={"tool_budget": {"max_web_search": 0}}),
                db,
            )
        assert exc.value.status_code == 422
    finally:
        db.query(SkillPack).filter(SkillPack.skill_pack_id == skill.skill_pack_id).delete()
        db.commit()
        db.close()
