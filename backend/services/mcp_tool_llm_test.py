"""LLM-driven single MCP tool test (instruction → forced tool_call → execute)."""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from models import ModelProvider, ModelService, ModelServiceStatus, ProviderStatus
from services.model_provider import model_provider_service

ExecuteToolFn = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]


def build_openai_tool_def_from_schema(
    tool_name: str,
    *,
    description: str = "",
    input_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    schema = input_schema if isinstance(input_schema, dict) else {}
    if schema.get("type") == "object" or schema.get("properties"):
        parameters = schema
    elif schema:
        parameters = {"type": "object", "properties": schema, "required": []}
    else:
        parameters = {"type": "object", "properties": {}, "required": []}
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description or f"Call MCP tool {tool_name}",
            "parameters": parameters,
        },
    }


def _safe_parse_tool_args(args_str: Any) -> Dict[str, Any]:
    if not args_str:
        return {}
    if isinstance(args_str, dict):
        return args_str
    if not isinstance(args_str, str):
        try:
            args_str = json.dumps(args_str, ensure_ascii=False)
        except (TypeError, ValueError):
            return {}
    try:
        data = json.loads(args_str)
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        return {"_raw": args_str}


def _content_to_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _parse_structured_tool_from_content(content: str) -> Optional[Dict[str, Any]]:
    if not content:
        return None

    def _normalize(data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        if "function" in data and isinstance(data.get("function"), dict):
            data = data["function"]
        name = data.get("tool_name") or data.get("tool") or data.get("name")
        if not name or not isinstance(name, str):
            return None
        args = data.get("arguments")
        if args is None:
            args = data.get("params")
        if args is None:
            args = data.get("parameters")
        if args is None:
            args = {}
        if isinstance(args, str):
            args = _safe_parse_tool_args(args)
        if not isinstance(args, dict):
            args = {"value": args}
        return {"name": name.strip(), "arguments": args}

    json_match = re.search(r"```json\s*\n?(.*?)\n?```", content, re.DOTALL)
    if json_match:
        try:
            normalized = _normalize(json.loads(json_match.group(1)))
            if normalized:
                return normalized
        except json.JSONDecodeError:
            pass

    json_match = re.search(
        r'\{[^{}]*"(?:tool_name|tool|name)"\s*:\s*"[^"]+"[^{}]*\}',
        content,
        re.DOTALL,
    )
    if json_match:
        try:
            normalized = _normalize(json.loads(json_match.group(0)))
            if normalized:
                return normalized
        except json.JSONDecodeError:
            pass
    return None


def extract_tool_call_from_llm_message(
    msg: Dict[str, Any],
    *,
    expected_tool_name: str,
) -> Optional[Dict[str, Any]]:
    tool_calls = msg.get("tool_calls") or []
    if isinstance(tool_calls, list):
        exact = None
        first = None
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = (fn.get("name") or "").strip()
            if not name:
                continue
            item = {
                "name": name,
                "arguments": _safe_parse_tool_args(fn.get("arguments")),
            }
            if first is None:
                first = item
            if name == expected_tool_name:
                exact = item
                break
        if exact:
            return exact
        if first:
            return first

    parsed = _parse_structured_tool_from_content(_content_to_str(msg.get("content")))
    if parsed:
        return parsed
    return None


async def run_mcp_tool_llm_test(
    db: Session,
    *,
    tool_name: str,
    instruction: str,
    model_service_id: str,
    input_schema: Optional[Dict[str, Any]] = None,
    tool_description: str = "",
    execute_tool: ExecuteToolFn,
) -> Dict[str, Any]:
    tool_name = (tool_name or "").strip()
    instruction = (instruction or "").strip()
    if not tool_name:
        return {"success": False, "error": "tool_name 必填", "tool_name": tool_name}
    if not instruction:
        return {"success": False, "error": "instruction 必填", "tool_name": tool_name}

    ms = (
        db.query(ModelService)
        .filter(ModelService.model_service_id == model_service_id)
        .first()
    )
    if not ms:
        return {"success": False, "error": "模型服务不存在", "tool_name": tool_name}
    if ms.status != ModelServiceStatus.ACTIVE:
        return {"success": False, "error": "模型服务未启用", "tool_name": tool_name}

    provider = (
        db.query(ModelProvider)
        .filter(ModelProvider.provider_id == ms.provider_id)
        .first()
    )
    if not provider or provider.status != ProviderStatus.ACTIVE:
        return {"success": False, "error": "模型供应商不可用", "tool_name": tool_name}

    tool_def = build_openai_tool_def_from_schema(
        tool_name,
        description=tool_description,
        input_schema=input_schema or {},
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是工具调用助手。你必须调用给定的函数工具来完成用户指令，"
                "不要只回复文字；根据指令填写合理参数。"
            ),
        },
        {"role": "user", "content": instruction},
    ]
    tool_choice = {"type": "function", "function": {"name": tool_name}}

    try:
        completion = await model_provider_service.chat_completion(
            provider,
            ms.model_name,
            messages,
            max_tokens=min(int(ms.max_tokens or 4096), 4096),
            temperature=0.2,
            tools=[tool_def],
            tool_choice=tool_choice,
            timeout_seconds=max(int(provider.timeout_seconds or 120), 60),
            source="mcp_tool_llm_test",
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"模型调用失败: {exc}",
            "tool_name": tool_name,
            "arguments": None,
            "tool_result": None,
            "llm_message": None,
        }

    choices = completion.get("choices") or []
    msg = (choices[0].get("message") if choices else {}) or {}
    llm_text = _content_to_str(msg.get("content"))
    parsed = extract_tool_call_from_llm_message(msg, expected_tool_name=tool_name)
    if not parsed:
        return {
            "success": False,
            "error": "模型未产生工具调用",
            "tool_name": tool_name,
            "arguments": None,
            "tool_result": None,
            "llm_message": llm_text or None,
        }

    called_name = parsed.get("name") or tool_name
    if called_name != tool_name:
        return {
            "success": False,
            "error": f"模型调用了错误的工具: {called_name}（期望 {tool_name}）",
            "tool_name": tool_name,
            "arguments": parsed.get("arguments") or {},
            "tool_result": None,
            "llm_message": llm_text or None,
        }

    arguments = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}
    tool_result = await execute_tool(tool_name, arguments)
    ok = bool(tool_result.get("success"))
    return {
        "success": ok,
        "tool_name": tool_name,
        "arguments": arguments,
        "tool_result": tool_result,
        "llm_message": llm_text or None,
        "error": None if ok else (tool_result.get("error") or "工具执行失败"),
    }
