"""Extract skill placeholder values from user utterances (rules + optional LLM)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.screenpilot.trajectory import (
    _CREDENTIAL_PARAM_KEYS,
    extract_search_query_hint,
)


def _schema_keys(param_schema: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(param_schema, dict):
        return []
    props = param_schema.get("properties") or {}
    if not isinstance(props, dict):
        return []
    required = param_schema.get("required") or list(props.keys())
    ordered: List[str] = []
    for k in required:
        if k in props and k not in ordered:
            ordered.append(k)
    for k in props:
        if k not in ordered:
            ordered.append(k)
    return ordered


def _schema_descriptions(param_schema: Optional[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    props = (param_schema or {}).get("properties") or {}
    if not isinstance(props, dict):
        return out
    for k, meta in props.items():
        if isinstance(meta, dict):
            out[k] = str(meta.get("description") or k)
        else:
            out[k] = str(k)
    return out


def apply_rule_extraction(
    user_text: str,
    keys: List[str],
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fill missing non-credential keys with search/query heuristics."""
    out = dict(existing or {})
    text = (user_text or "").strip()
    if not text or not keys:
        return out

    # Param key -> natural-language labels commonly used in user instructions.
    key_aliases: Dict[str, List[str]] = {
        "title": ["title", "标题", "题目", "贴文标题"],
        "text": ["text", "正文", "内容", "正文内容", "帖文", "贴文", "body", "content"],
        "content": ["content", "正文", "内容", "text", "body", "帖文", "贴文"],
        "body": ["body", "正文", "内容", "text", "content"],
        "query": ["query", "关键词", "搜索词", "搜索"],
        "name": ["name", "名称", "姓名"],
    }

    def _aliases_for(key: str) -> List[str]:
        low = key.lower()
        aliases = list(key_aliases.get(low) or [])
        if key not in aliases:
            aliases.insert(0, key)
        # Also try bare key for unknown params.
        if low not in key_aliases and low not in aliases:
            aliases.append(key)
        # Dedupe preserve order
        seen = set()
        ordered: List[str] = []
        for a in aliases:
            if a and a not in seen:
                seen.add(a)
                ordered.append(a)
        return ordered

    def _extract_labeled(labels: List[str]) -> Optional[str]:
        for lab in labels:
            # 标题：“xxx” / 标题: xxx / title=xxx
            pat = (
                rf"(?:{re.escape(lab)})\s*[:=：]\s*"
                rf"[「\"'“]?([^」\"'”\n，,；;]+)"
            )
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip().strip("「」\"'“” ")
                if val:
                    return val
        return None

    hint = extract_search_query_hint(text)
    for key in keys:
        if key.lower() in _CREDENTIAL_PARAM_KEYS:
            continue
        if str(out.get(key) or "").strip():
            continue
        if key == "query" and hint:
            out[key] = hint
            continue
        labeled = _extract_labeled(_aliases_for(key))
        if labeled:
            out[key] = labeled
            continue
        # key:value / 参数 key ：value (ASCII key only)
        m = re.search(
            rf"(?:{re.escape(key)}|参数\s*{re.escape(key)})\s*[:=：]\s*([^\s,，;；]+)",
            text,
            re.IGNORECASE,
        )
        if m:
            out[key] = m.group(1).strip().strip("「」\"'“”")
            continue
        if hint and len([k for k in keys if k.lower() not in _CREDENTIAL_PARAM_KEYS]) == 1:
            out[key] = hint
    return out


def _parse_llm_json(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


async def _llm_extract_params(
    db: Session,
    *,
    user_text: str,
    missing_keys: List[str],
    descriptions: Dict[str, str],
    step_hints: Optional[List[str]] = None,
) -> Dict[str, str]:
    if not missing_keys or not (user_text or "").strip():
        return {}
    try:
        from models import ModelProvider, ModelService, ModelServiceStatus, ProviderStatus
        from services.model_provider import model_provider_service

        svc = (
            db.query(ModelService)
            .filter(ModelService.status == ModelServiceStatus.ACTIVE)
            .order_by(ModelService.updated_at.desc())
            .first()
        )
        if not svc:
            return {}
        provider = (
            db.query(ModelProvider)
            .filter(
                ModelProvider.provider_id == svc.provider_id,
                ModelProvider.status == ProviderStatus.ACTIVE,
            )
            .first()
        )
        if not provider:
            return {}

        fields = [
            {"key": k, "description": descriptions.get(k) or k}
            for k in missing_keys
        ]
        hints = "\n".join(f"- {h}" for h in (step_hints or [])[:12])
        prompt = (
            "从用户话术中抽取 UI 技能参数。只返回 JSON 对象，键为参数名，值为字符串；"
            "无法确定的键不要编造，可省略。\n"
            f"参数定义：{json.dumps(fields, ensure_ascii=False)}\n"
            f"步骤提示：\n{hints or '(无)'}\n"
            f"用户话术：{user_text[:800]}\n"
            "JSON:"
        )
        completion = await model_provider_service.chat_completion(
            provider,
            svc.model_name,
            [
                {"role": "system", "content": "你是参数抽取器，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=min(int(svc.max_tokens or 512), 800),
            temperature=0.0,
        )
        content = ""
        choices = completion.get("choices") or []
        if choices:
            content = ((choices[0].get("message") or {}).get("content") or "").strip()
        raw = _parse_llm_json(content)
        cleaned: Dict[str, str] = {}
        for k in missing_keys:
            v = raw.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() not in ("null", "none", "未知", "不清楚"):
                cleaned[k] = s
        return cleaned
    except Exception:
        return {}


async def extract_skill_params(
    db: Optional[Session] = None,
    *,
    user_text: str,
    param_schema: Optional[Dict[str, Any]] = None,
    existing: Optional[Dict[str, Any]] = None,
    step_hints: Optional[List[str]] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    Returns { values, missing, filled_keys }.
    Never invents credential fields (username/password/otp/...).
    """
    keys = _schema_keys(param_schema)
    values = apply_rule_extraction(user_text, keys, existing)

    missing = [
        k
        for k in keys
        if k.lower() not in _CREDENTIAL_PARAM_KEYS and not str(values.get(k) or "").strip()
    ]
    if use_llm and missing and db is not None:
        descriptions = _schema_descriptions(param_schema)
        llm_vals = await _llm_extract_params(
            db,
            user_text=user_text,
            missing_keys=missing,
            descriptions=descriptions,
            step_hints=step_hints,
        )
        for k, v in llm_vals.items():
            if not str(values.get(k) or "").strip():
                values[k] = v
        missing = [
            k
            for k in keys
            if k.lower() not in _CREDENTIAL_PARAM_KEYS and not str(values.get(k) or "").strip()
        ]

    filled = [
        k
        for k in keys
        if k.lower() not in _CREDENTIAL_PARAM_KEYS and str(values.get(k) or "").strip()
    ]
    return {"values": values, "missing": missing, "filled_keys": filled}
