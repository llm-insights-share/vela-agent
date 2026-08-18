"""Extract and match knowledge-base document tags."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DATE_PATTERNS = [
    re.compile(r"(20\d{2})[./\-年](\d{1,2})[./\-月](\d{1,2})日?"),
    re.compile(r"(20\d{2})(\d{2})(\d{2})"),
]

NEAR_EXPIRE_RE = re.compile(
    r"(失效|废止|施行|有效期至|有效期到).{0,24}?(20\d{2}[./\-年]\d{1,2}[./\-月]\d{1,2}日?)",
    re.S,
)

VALID_QUERY_RE = re.compile(r"现行|有效|未失效|仍适用|未废止")
EXPIRED_QUERY_RE = re.compile(r"已失效|已废止|已过期|失效的|废止的|过期的")
EXPIRE_NAME_RE = re.compile(r"失效|过期|废止")

EXTRACT_PROMPT = """根据文档内容，抽取下列标签的值。只输出 JSON 对象，不要其它文字。
找不到的字段请输出空字符串。日期统一为 YYYY/MM/DD。

标签定义:
{tag_schema}

文件名: {filename}

<document>
{excerpt}
</document>
"""

SUGGEST_PROMPT = """根据用户检索语句，为知识库标签生成可选过滤条件。只输出 JSON 数组。
每项格式: {{"name":"标签名","op":"eq|contains|gte|lte|lt|gt","value":"..."}}
只使用下列已定义标签；抽不到的不要输出。日期用 YYYY/MM/DD。
问现行/有效制度时，失效类日期标签用 gte 今天；问已废止/已失效时用 lt 今天。

今天: {today}
标签定义: {tag_schema}
用户查询: {query}
"""


def infer_tag_type(name: str, explicit: str = "") -> str:
    if explicit in ("text", "date"):
        return explicit
    if re.search(r"时间|日期|日", name or ""):
        return "date"
    return "text"


def normalize_tag_defs(raw: Optional[Iterable[Any]]) -> List[Dict[str, str]]:
    defs: List[Dict[str, str]] = []
    seen = set()
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            hint = str(item.get("hint") or "").strip()
            typ = infer_tag_type(name, str(item.get("type") or "").strip())
        else:
            name = str(getattr(item, "name", "") or "").strip()
            hint = str(getattr(item, "hint", "") or "").strip()
            typ = infer_tag_type(name, str(getattr(item, "type", "") or "").strip())
        if not name or name in seen:
            continue
        seen.add(name)
        defs.append({"name": name, "type": typ, "hint": hint})
    return defs


def normalize_date(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        try:
            parsed = date(year, month, day)
        except ValueError:
            continue
        return parsed.strftime("%Y/%m/%d")
    return ""


def today_str() -> str:
    return date.today().strftime("%Y/%m/%d")


def parse_date(value: str) -> Optional[date]:
    normalized = normalize_date(value)
    if not normalized:
        return None
    return datetime.strptime(normalized, "%Y/%m/%d").date()


def format_tags_index_line(tags: Optional[Dict[str, Any]]) -> str:
    parts = []
    for key, value in (tags or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        parts.append(f"{key}={text}")
    if not parts:
        return ""
    return "标签：" + "；".join(parts)


def apply_tags_to_index_text(index_text: str, tags: Optional[Dict[str, Any]]) -> str:
    line = format_tags_index_line(tags)
    if not line:
        return index_text
    if index_text.startswith(line):
        return index_text
    return f"{line}\n\n{index_text}"


def _expire_tag_names(tag_defs: List[Dict[str, str]]) -> List[str]:
    return [
        d["name"]
        for d in tag_defs
        if d.get("type") == "date" and EXPIRE_NAME_RE.search(d["name"])
    ]


def heuristic_extract_dates(text: str, filename: str = "") -> Dict[str, str]:
    blob = f"{filename}\n{text or ''}"
    found: List[str] = []
    for match in DATE_PATTERNS[0].finditer(blob):
        normalized = normalize_date(match.group(0))
        if normalized and normalized not in found:
            found.append(normalized)
    near = []
    for match in NEAR_EXPIRE_RE.finditer(blob):
        normalized = normalize_date(match.group(2))
        if normalized:
            near.append(normalized)
    return {"all": found, "near_expire": near}


def extract_tags_heuristic(
    tag_defs: List[Dict[str, str]],
    document_text: str,
    filename: str = "",
) -> List[Dict[str, str]]:
    dates = heuristic_extract_dates(document_text, filename)
    results = []
    for definition in tag_defs:
        name = definition["name"]
        typ = definition["type"]
        value = ""
        source = "empty"
        if typ == "date":
            if EXPIRE_NAME_RE.search(name) and dates["near_expire"]:
                value = dates["near_expire"][0]
                source = "heuristic"
            elif "创建" in name:
                value = today_str()
                source = "heuristic"
            elif dates["all"]:
                value = dates["all"][0]
                source = "heuristic"
        results.append({
            "name": name,
            "type": typ,
            "value": value,
            "source": source,
        })
    return results


def _extract_json_payload(text: str):
    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start_obj = raw.find("{")
        end_obj = raw.rfind("}")
        start_arr = raw.find("[")
        end_arr = raw.rfind("]")
        snippet = ""
        if start_arr != -1 and end_arr > start_arr and (start_obj == -1 or start_arr < start_obj):
            snippet = raw[start_arr:end_arr + 1]
        elif start_obj != -1 and end_obj > start_obj:
            snippet = raw[start_obj:end_obj + 1]
        if snippet:
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                return None
        return None


async def extract_tags(
    tag_defs: List[Dict[str, str]],
    document_text: str,
    filename: str = "",
    db: Optional[Session] = None,
    model_service_id: str = "",
) -> List[Dict[str, str]]:
    defs = normalize_tag_defs(tag_defs)
    merged = {item["name"]: item for item in extract_tags_heuristic(defs, document_text, filename)}
    if not defs:
        return []

    try:
        llm_values = await _llm_extract_tag_values(
            defs, document_text, filename, db, model_service_id
        )
    except Exception as exc:
        logger.warning("[tag_extractor] extract_tags LLM failed: %s", exc)
        llm_values = {}
    for name, value in llm_values.items():
        if name not in merged:
            continue
        definition = next(d for d in defs if d["name"] == name)
        cleaned = normalize_date(value) if definition["type"] == "date" else str(value or "").strip()
        if cleaned:
            merged[name]["value"] = cleaned
            merged[name]["source"] = "llm"
    return [merged[d["name"]] for d in defs]


async def _llm_extract_tag_values(
    tag_defs: List[Dict[str, str]],
    document_text: str,
    filename: str,
    db: Optional[Session],
    model_service_id: str,
) -> Dict[str, str]:
    if db is None:
        return {}
    try:
        from services.knowledge.config import load_contextual_retrieval_config
        from services.knowledge.contextualizer import resolve_model_service
        from services.model_provider import ModelProviderService

        cfg = load_contextual_retrieval_config()
        resolved = resolve_model_service(db, model_service_id or cfg.model_service_id)
        if resolved is None:
            return {}
        provider, model_svc = resolved
        excerpt = (document_text or "").strip()[:3000]
        schema = json.dumps(tag_defs, ensure_ascii=False)
        prompt = EXTRACT_PROMPT.format(
            tag_schema=schema,
            filename=filename or "",
            excerpt=excerpt,
        )
        completion = await ModelProviderService.chat_completion(
            provider=provider,
            model_name=model_svc.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.0,
            timeout_seconds=min(cfg.chunk_timeout_seconds, 30),
            source="kb_tag_extract",
        )
        content = ((completion.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        payload = _extract_json_payload(content)
        if not isinstance(payload, dict):
            return {}
        return {str(k): str(v or "") for k, v in payload.items()}
    except Exception as exc:
        logger.warning("[tag_extractor] LLM extract failed: %s", exc)
        return {}


def suggest_tag_filters_heuristic(
    query: str,
    tag_defs: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    defs = normalize_tag_defs(tag_defs)
    expire_names = _expire_tag_names(defs)
    if not expire_names:
        return []
    if EXPIRED_QUERY_RE.search(query or ""):
        return [{"name": expire_names[0], "op": "lt", "value": today_str()}]
    if VALID_QUERY_RE.search(query or ""):
        return [{"name": expire_names[0], "op": "gte", "value": today_str()}]
    return []


async def suggest_tag_filters(
    query: str,
    tag_defs: List[Dict[str, str]],
    db: Optional[Session] = None,
    model_service_id: str = "",
) -> List[Dict[str, str]]:
    defs = normalize_tag_defs(tag_defs)
    allowed = {d["name"]: d for d in defs}
    merged = {item["name"]: item for item in suggest_tag_filters_heuristic(query, defs)}
    try:
        llm_filters = await _llm_suggest_filters(query, defs, db, model_service_id)
    except Exception as exc:
        logger.warning("[tag_extractor] suggest_tag_filters LLM failed: %s", exc)
        llm_filters = []
    for item in llm_filters:
        name = item.get("name")
        if name in allowed:
            merged[name] = item
    out = []
    for name, item in merged.items():
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        definition = allowed[name]
        op = str(item.get("op") or "eq").strip()
        if definition["type"] == "date":
            value = normalize_date(value) or value
            if op not in ("eq", "gte", "lte", "lt", "gt"):
                op = "eq"
        else:
            if op not in ("eq", "contains"):
                op = "eq"
        out.append({"name": name, "op": op, "value": value})
    return out


async def _llm_suggest_filters(
    query: str,
    tag_defs: List[Dict[str, str]],
    db: Optional[Session],
    model_service_id: str,
) -> List[Dict[str, str]]:
    if db is None or not query.strip():
        return []
    try:
        from services.knowledge.config import load_contextual_retrieval_config
        from services.knowledge.contextualizer import resolve_model_service
        from services.model_provider import ModelProviderService

        cfg = load_contextual_retrieval_config()
        resolved = resolve_model_service(db, model_service_id or cfg.model_service_id)
        if resolved is None:
            return []
        provider, model_svc = resolved
        prompt = SUGGEST_PROMPT.format(
            today=today_str(),
            tag_schema=json.dumps(tag_defs, ensure_ascii=False),
            query=query,
        )
        completion = await ModelProviderService.chat_completion(
            provider=provider,
            model_name=model_svc.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.0,
            timeout_seconds=min(cfg.chunk_timeout_seconds, 20),
            source="kb_tag_suggest",
        )
        content = ((completion.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        payload = _extract_json_payload(content)
        if not isinstance(payload, list):
            return []
        out = []
        for item in payload:
            if isinstance(item, dict) and item.get("name"):
                out.append({
                    "name": str(item.get("name") or "").strip(),
                    "op": str(item.get("op") or "eq").strip(),
                    "value": str(item.get("value") or "").strip(),
                })
        return out
    except Exception as exc:
        logger.warning("[tag_extractor] LLM suggest failed: %s", exc)
        return []


def normalize_tag_filters(raw: Optional[Iterable[Any]]) -> List[Dict[str, str]]:
    filters = []
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            op = str(item.get("op") or "eq").strip()
            value = str(item.get("value") or "").strip()
        else:
            name = str(getattr(item, "name", "") or "").strip()
            op = str(getattr(item, "op", "eq") or "eq").strip()
            value = str(getattr(item, "value", "") or "").strip()
        if not name or not value:
            continue
        filters.append({"name": name, "op": op or "eq", "value": value})
    return filters


def tag_value_matches(stored: Any, op: str, expected: str, value_type: str = "text") -> bool:
    text = str(stored or "").strip()
    if value_type == "date" and op in ("gte", "gt", "lte", "lt"):
        left = parse_date(text)
        right = parse_date(expected)
        if left is None or right is None:
            return True
        if op == "gte":
            return left >= right
        if op == "gt":
            return left > right
        if op == "lte":
            return left <= right
        return left < right
    if not text:
        return False
    if value_type == "date":
        left = parse_date(text)
        right = parse_date(expected)
        if left is None or right is None:
            return False
        if op == "eq":
            return left == right
    if op == "contains":
        return expected in text
    return text == expected


def document_matches_tag_filters(
    tags: Optional[Dict[str, Any]],
    tag_filters: List[Dict[str, str]],
    tag_defs: Optional[List[Dict[str, str]]] = None,
) -> bool:
    filters = normalize_tag_filters(tag_filters)
    if not filters:
        return True
    type_by_name = {d["name"]: d["type"] for d in normalize_tag_defs(tag_defs)}
    current = tags or {}
    for item in filters:
        name = item["name"]
        op = item["op"]
        expected = item["value"]
        typ = type_by_name.get(name) or infer_tag_type(name)
        if not tag_value_matches(current.get(name), op, expected, typ):
            return False
    return True
