"""保错采样：失败/护栏/差评全量保留，成功 run 可按比例降采样正文。"""

from __future__ import annotations

import os
from typing import Any, Dict, List

SUCCESS_SAMPLE_RATE = float(os.getenv("MONITOR_SUCCESS_SAMPLE_RATE", "1.0"))


def should_sample_content(*, status: str, guard_blocked: bool = False) -> bool:
    if status not in ("SUCCESS",):
        return True
    if guard_blocked:
        return True
    if SUCCESS_SAMPLE_RATE >= 1.0:
        return True
    import random

    return random.random() < SUCCESS_SAMPLE_RATE


def redact_span_attrs(attrs: Dict[str, Any], *, keep_full: bool) -> Dict[str, Any]:
    if keep_full or not attrs:
        return dict(attrs or {})
    out = dict(attrs)
    for key in ("input", "output", "messages", "content", "thinking"):
        val = out.get(key)
        if isinstance(val, str) and len(val) > 500:
            out[key] = val[:500] + "…[truncated]"
        elif isinstance(val, list) and len(val) > 5:
            out[key] = val[:5]
            out[f"{key}_truncated"] = True
    return out


def redact_spans(spans: List[Dict[str, Any]], *, keep_full: bool) -> List[Dict[str, Any]]:
    return [
        {
            **s,
            "attrs_json": redact_span_attrs(s.get("attrs_json") or {}, keep_full=keep_full),
        }
        for s in spans
    ]
