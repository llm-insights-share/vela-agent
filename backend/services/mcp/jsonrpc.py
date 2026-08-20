from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional


class McpError(Exception):
    def __init__(self, message: str, *, status_code: int = 0, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class McpAuthError(McpError):
    def __init__(self, message: str, *, www_authenticate: str = "", status_code: int = 401):
        super().__init__(message, status_code=status_code)
        self.www_authenticate = www_authenticate or ""


def make_request(req_id: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def make_notification(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def extract_result(message: Dict[str, Any]) -> Any:
    if not isinstance(message, dict):
        raise McpError(f"无效的 JSON-RPC 响应: {message!r}")
    if message.get("error"):
        err = message["error"]
        if isinstance(err, dict):
            raise McpError(err.get("message") or json.dumps(err, ensure_ascii=False), payload=err)
        raise McpError(str(err), payload=err)
    return message.get("result")


def parse_sse_events(text: str) -> List[Dict[str, str]]:
    events: List[Dict[str, str]] = []
    event_type = "message"
    data_lines: List[str] = []

    def flush():
        nonlocal event_type, data_lines
        if data_lines:
            events.append({"event": event_type or "message", "data": "\n".join(data_lines)})
        event_type = "message"
        data_lines = []

    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        if line == "":
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_type = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()
    return events


def iter_sse_json_messages(text: str) -> Iterator[Dict[str, Any]]:
    for event in parse_sse_events(text):
        data = (event.get("data") or "").strip()
        if not data:
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield parsed


def jsonrpc_from_http_body(content_type: str, text: str, req_id: Optional[int] = None) -> Dict[str, Any]:
    ct = (content_type or "").lower()
    if "text/event-stream" in ct:
        last: Optional[Dict[str, Any]] = None
        for msg in iter_sse_json_messages(text):
            if req_id is None or msg.get("id") == req_id or "error" in msg or "result" in msg:
                last = msg
                if req_id is not None and msg.get("id") == req_id:
                    return msg
        if last is not None:
            return last
        raise McpError("SSE 响应中没有 JSON-RPC 消息")
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise McpError(f"无法解析 MCP 响应: {exc}") from exc
    if not isinstance(data, dict):
        raise McpError("MCP 响应不是 JSON 对象")
    return data


def encode_ndjson(payload: Dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def decode_ndjson_line(line: bytes) -> Optional[Dict[str, Any]]:
    text = (line or b"").decode("utf-8", errors="replace").strip()
    if not text:
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise McpError("stdio 响应不是 JSON 对象")
    return data
