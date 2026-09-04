"""OpenInference semantic attribute builders and kind↔UI mappings."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

try:
    from openinference.semconv.trace import (
        MessageAttributes,
        OpenInferenceSpanKindValues,
        SpanAttributes,
        ToolAttributes,
        ToolCallAttributes,
        DocumentAttributes,
    )
except ImportError:  # pragma: no cover - fallback when package missing

    class _S:
        OPENINFERENCE_SPAN_KIND = "openinference.span.kind"
        INPUT_VALUE = "input.value"
        INPUT_MIME_TYPE = "input.mime_type"
        OUTPUT_VALUE = "output.value"
        OUTPUT_MIME_TYPE = "output.mime_type"
        LLM_MODEL_NAME = "llm.model_name"
        LLM_INVOCATION_PARAMETERS = "llm.invocation_parameters"
        LLM_INPUT_MESSAGES = "llm.input_messages"
        LLM_OUTPUT_MESSAGES = "llm.output_messages"
        LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
        LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
        LLM_TOKEN_COUNT_TOTAL = "llm.token_count.total"
        LLM_TOOLS = "llm.tools"
        TOOL_NAME = "tool.name"
        TOOL_DESCRIPTION = "tool.description"
        TOOL_PARAMETERS = "tool.parameters"
        SESSION_ID = "session.id"
        USER_ID = "user.id"
        METADATA = "metadata"
        RETRIEVAL_DOCUMENTS = "retrieval.documents"

    class _M:
        MESSAGE_ROLE = "message.role"
        MESSAGE_CONTENT = "message.content"
        MESSAGE_TOOL_CALLS = "message.tool_calls"
        MESSAGE_TOOL_CALL_ID = "message.tool_call_id"
        MESSAGE_NAME = "message.name"

    class _TC:
        TOOL_CALL_ID = "tool_call.id"
        TOOL_CALL_FUNCTION_NAME = "tool_call.function.name"
        TOOL_CALL_FUNCTION_ARGUMENTS_JSON = "tool_call.function.arguments"

    class _T:
        TOOL_JSON_SCHEMA = "tool.json_schema"

    class _D:
        DOCUMENT_ID = "document.id"
        DOCUMENT_CONTENT = "document.content"
        DOCUMENT_SCORE = "document.score"
        DOCUMENT_METADATA = "document.metadata"

    class OpenInferenceSpanKindValues:
        LLM = type("E", (), {"value": "LLM"})()
        TOOL = type("E", (), {"value": "TOOL"})()
        AGENT = type("E", (), {"value": "AGENT"})()
        CHAIN = type("E", (), {"value": "CHAIN"})()
        GUARDRAIL = type("E", (), {"value": "GUARDRAIL"})()
        RETRIEVER = type("E", (), {"value": "RETRIEVER"})()
        EVALUATOR = type("E", (), {"value": "EVALUATOR"})()
        EMBEDDING = type("E", (), {"value": "EMBEDDING"})()

    SpanAttributes = _S()
    MessageAttributes = _M()
    ToolCallAttributes = _TC()
    ToolAttributes = type("T", (), {"TOOL_JSON_SCHEMA": "tool.json_schema"})()
    DocumentAttributes = _D()


# UI / Postgres legacy kind column
OI_TO_LEGACY_KIND = {
    "AGENT": "agent",
    "LLM": "chat",
    "TOOL": "execute_tool",
    "GUARDRAIL": "guard_decision",
    "CHAIN": "internal",
    "RETRIEVER": "retriever",
    "EVALUATOR": "evaluator",
    "EMBEDDING": "embedding",
    "PROMPT": "internal",
    "RERANKER": "internal",
}

LEGACY_TO_OI_KIND = {v: k for k, v in OI_TO_LEGACY_KIND.items()}
LEGACY_TO_OI_KIND.update(
    {
        "internal": "CHAIN",
        "chat": "LLM",
        "execute_tool": "TOOL",
        "guard_decision": "GUARDRAIL",
    }
)


def oi_kind_value(kind: Union[str, Any]) -> str:
    if hasattr(kind, "value"):
        return str(kind.value)
    return str(kind)


def legacy_kind_for_oi(oi_kind: str) -> str:
    return OI_TO_LEGACY_KIND.get(oi_kind, "internal")


def oi_kind_from_legacy(legacy: str) -> str:
    return LEGACY_TO_OI_KIND.get(legacy or "", "CHAIN")


def _json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(obj)


def flatten_dict(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dicts/lists into OpenInference-style dotted keys."""
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten_dict(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}.{i}" if prefix else str(i)
            out.update(flatten_dict(v, key))
    else:
        if prefix:
            out[prefix] = obj
    return out


def _set(attrs: Dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    attrs[key] = value


def session_context_attrs(
    *,
    session_id: str = "",
    user_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    attrs: Dict[str, Any] = {}
    sid = getattr(SpanAttributes, "SESSION_ID", "session.id")
    uid = getattr(SpanAttributes, "USER_ID", "user.id")
    meta_key = getattr(SpanAttributes, "METADATA", "metadata")
    if session_id:
        attrs[sid] = session_id
    if user_id:
        attrs[uid] = user_id
    if metadata:
        attrs[meta_key] = _json_dumps(metadata)
    return attrs


def attrs_for_agent(
    *,
    session_id: str = "",
    user_id: str = "",
    agent_id: str = "",
    input_text: str = "",
    output_text: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    attrs = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: oi_kind_value(OpenInferenceSpanKindValues.AGENT),
        **session_context_attrs(session_id=session_id, user_id=user_id, metadata=metadata),
    }
    if agent_id:
        attrs["agent.id"] = agent_id
    if input_text:
        attrs[SpanAttributes.INPUT_VALUE] = input_text
        attrs[SpanAttributes.INPUT_MIME_TYPE] = "text/plain"
    if output_text:
        attrs[SpanAttributes.OUTPUT_VALUE] = output_text
        attrs[SpanAttributes.OUTPUT_MIME_TYPE] = "text/plain"
    return attrs


def _message_attrs(prefix: str, msg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    role = msg.get("role") or "unknown"
    out[f"{prefix}.{MessageAttributes.MESSAGE_ROLE}"] = role
    content = msg.get("content")
    if content is not None:
        if not isinstance(content, str):
            content = _json_dumps(content)
        out[f"{prefix}.{MessageAttributes.MESSAGE_CONTENT}"] = content[:8000]
    if role in ("tool", "function"):
        if msg.get("tool_call_id"):
            out[f"{prefix}.{MessageAttributes.MESSAGE_TOOL_CALL_ID}"] = msg["tool_call_id"]
        if msg.get("name"):
            out[f"{prefix}.{MessageAttributes.MESSAGE_NAME}"] = msg["name"]
    tool_calls = msg.get("tool_calls") or []
    for i, tc in enumerate(tool_calls):
        fn = tc.get("function") or {}
        base = f"{prefix}.{MessageAttributes.MESSAGE_TOOL_CALLS}.{i}"
        if tc.get("id"):
            out[f"{base}.{ToolCallAttributes.TOOL_CALL_ID}"] = tc["id"]
        name = fn.get("name") or tc.get("name")
        if name:
            out[f"{base}.{ToolCallAttributes.TOOL_CALL_FUNCTION_NAME}"] = name
        args = fn.get("arguments")
        if args is not None:
            if not isinstance(args, str):
                args = _json_dumps(args)
            out[f"{base}.{ToolCallAttributes.TOOL_CALL_FUNCTION_ARGUMENTS_JSON}"] = args[:4000]
    return out


def attrs_for_llm_call(
    *,
    model_name: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    output_content: Optional[str] = None,
    output_tool_calls: Optional[List[Dict[str, Any]]] = None,
    usage: Optional[Dict[str, Any]] = None,
    raw_error: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    attrs: Dict[str, Any] = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: oi_kind_value(OpenInferenceSpanKindValues.LLM),
    }
    if model_name:
        attrs[SpanAttributes.LLM_MODEL_NAME] = model_name
    inv: Dict[str, Any] = {}
    if max_tokens is not None:
        inv["max_tokens"] = max_tokens
    if temperature is not None:
        inv["temperature"] = temperature
    if source:
        inv["source"] = source
    if inv:
        attrs[SpanAttributes.LLM_INVOCATION_PARAMETERS] = _json_dumps(inv)

    messages = messages or []
    for i, msg in enumerate(messages):
        if isinstance(msg, dict):
            attrs.update(_message_attrs(f"{SpanAttributes.LLM_INPUT_MESSAGES}.{i}", msg))

    if tools:
        for i, tool in enumerate(tools):
            schema = tool if isinstance(tool, dict) else {"name": str(tool)}
            key = f"{SpanAttributes.LLM_TOOLS}.{i}.{getattr(ToolAttributes, 'TOOL_JSON_SCHEMA', 'tool.json_schema')}"
            attrs[key] = _json_dumps(schema)

    attrs[SpanAttributes.INPUT_VALUE] = _json_dumps({"messages": messages, "tools": tools})[:12000]
    attrs[SpanAttributes.INPUT_MIME_TYPE] = "application/json"

    out_msg: Dict[str, Any] = {"role": "assistant"}
    if output_content is not None:
        out_msg["content"] = output_content
    if output_tool_calls:
        out_msg["tool_calls"] = output_tool_calls
    if raw_error:
        out_msg["content"] = (out_msg.get("content") or "") or raw_error
    attrs.update(_message_attrs(f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0", out_msg))
    attrs[SpanAttributes.OUTPUT_VALUE] = _json_dumps(out_msg)[:8000]
    attrs[SpanAttributes.OUTPUT_MIME_TYPE] = "application/json"

    usage = usage or {}
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
    completion = usage.get("completion_tokens") or usage.get("output_tokens")
    total = usage.get("total_tokens")
    if prompt is not None:
        attrs[SpanAttributes.LLM_TOKEN_COUNT_PROMPT] = int(prompt)
    if completion is not None:
        attrs[SpanAttributes.LLM_TOKEN_COUNT_COMPLETION] = int(completion)
    if total is not None:
        attrs[SpanAttributes.LLM_TOKEN_COUNT_TOTAL] = int(total)
    elif prompt is not None and completion is not None:
        attrs[SpanAttributes.LLM_TOKEN_COUNT_TOTAL] = int(prompt) + int(completion)
    return attrs


def attrs_for_tool(
    *,
    tool_name: str,
    tool_description: str = "",
    parameters: Any = None,
    output: Any = None,
) -> Dict[str, Any]:
    tool_name_key = getattr(SpanAttributes, "TOOL_NAME", "tool.name")
    tool_desc_key = getattr(SpanAttributes, "TOOL_DESCRIPTION", "tool.description")
    tool_params_key = getattr(SpanAttributes, "TOOL_PARAMETERS", "tool.parameters")
    attrs: Dict[str, Any] = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: oi_kind_value(OpenInferenceSpanKindValues.TOOL),
        tool_name_key: tool_name or "unknown",
    }
    if tool_description:
        attrs[tool_desc_key] = tool_description[:2000]
    if parameters is not None:
        params_s = parameters if isinstance(parameters, str) else _json_dumps(parameters)
        attrs[tool_params_key] = params_s[:4000]
        attrs[SpanAttributes.INPUT_VALUE] = params_s[:8000]
        attrs[SpanAttributes.INPUT_MIME_TYPE] = "application/json"
    if output is not None:
        out_s = output if isinstance(output, str) else _json_dumps(output)
        attrs[SpanAttributes.OUTPUT_VALUE] = out_s[:8000]
        attrs[SpanAttributes.OUTPUT_MIME_TYPE] = "application/json"
    return attrs


def attrs_for_guardrail(
    *,
    checkpoint: str = "",
    decision: str = "",
    reason: str = "",
    action: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "checkpoint": checkpoint,
        "decision": decision,
        "reason": reason,
        "action": action,
        **(extra or {}),
    }
    attrs: Dict[str, Any] = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: oi_kind_value(OpenInferenceSpanKindValues.GUARDRAIL),
        SpanAttributes.INPUT_VALUE: _json_dumps({"checkpoint": checkpoint}),
        SpanAttributes.INPUT_MIME_TYPE: "application/json",
        SpanAttributes.OUTPUT_VALUE: _json_dumps(payload),
        SpanAttributes.OUTPUT_MIME_TYPE: "application/json",
        getattr(SpanAttributes, "METADATA", "metadata"): _json_dumps(payload),
    }
    return attrs


def attrs_for_retriever(
    *,
    query: str,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    retrieval_key = getattr(SpanAttributes, "RETRIEVAL_DOCUMENTS", "retrieval.documents")
    attrs: Dict[str, Any] = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: oi_kind_value(OpenInferenceSpanKindValues.RETRIEVER),
        SpanAttributes.INPUT_VALUE: query or "",
        SpanAttributes.INPUT_MIME_TYPE: "text/plain",
    }
    docs = documents or []
    for i, doc in enumerate(docs):
        base = f"{retrieval_key}.{i}"
        doc_id = doc.get("chunk_id") or doc.get("id") or doc.get("document_id") or str(i)
        attrs[f"{base}.{DocumentAttributes.DOCUMENT_ID}"] = str(doc_id)
        content = doc.get("content") or doc.get("text") or ""
        attrs[f"{base}.{DocumentAttributes.DOCUMENT_CONTENT}"] = str(content)[:4000]
        if doc.get("score") is not None:
            attrs[f"{base}.{DocumentAttributes.DOCUMENT_SCORE}"] = float(doc["score"])
        meta = doc.get("metadata")
        if meta is not None:
            attrs[f"{base}.{DocumentAttributes.DOCUMENT_METADATA}"] = _json_dumps(meta)
    attrs[SpanAttributes.OUTPUT_VALUE] = _json_dumps(
        [{"id": d.get("chunk_id") or d.get("id"), "score": d.get("score")} for d in docs]
    )[:8000]
    attrs[SpanAttributes.OUTPUT_MIME_TYPE] = "application/json"
    return attrs


def attrs_for_evaluator(
    *,
    name: str,
    score: Optional[float] = None,
    label: str = "",
    explanation: str = "",
    input_text: str = "",
) -> Dict[str, Any]:
    attrs: Dict[str, Any] = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: oi_kind_value(OpenInferenceSpanKindValues.EVALUATOR),
    }
    if input_text:
        attrs[SpanAttributes.INPUT_VALUE] = input_text[:4000]
        attrs[SpanAttributes.INPUT_MIME_TYPE] = "text/plain"
    eval_payload = {
        "evaluation.name": name,
        "evaluation.score": score,
        "evaluation.label": label,
        "evaluation.explanation": explanation,
    }
    attrs["evaluations.0.evaluation.name"] = name
    if score is not None:
        attrs["evaluations.0.evaluation.score"] = float(score)
    if label:
        attrs["evaluations.0.evaluation.label"] = label
    if explanation:
        attrs["evaluations.0.evaluation.explanation"] = explanation[:2000]
    attrs[SpanAttributes.OUTPUT_VALUE] = _json_dumps(eval_payload)
    attrs[SpanAttributes.OUTPUT_MIME_TYPE] = "application/json"
    return attrs


def otel_attribute_pairs(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce values to OTEL-friendly primitives."""
    out: Dict[str, Any] = {}
    for k, v in (attrs or {}).items():
        if v is None:
            continue
        if isinstance(v, (bool, int, float, str)):
            out[k] = v
        else:
            out[k] = _json_dumps(v)
    return out
