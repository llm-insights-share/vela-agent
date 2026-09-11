"""LLM reflection engine — structured findings (no free-form-only advice)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import Agent, ModelProvider, ModelService
from services.model_provider import ModelProviderService
from services.selfopt.risk import CHANGE_KIND_TIERS, is_forbidden_change_kind


REFLECT_SYSTEM = """你是 Vela SelfOpt 反思引擎。根据 Agent 失败/次优轨迹，输出严格 JSON（不要 markdown）：
{
  "findings": [
    {
      "failure_mode": "简短归因标签",
      "cited_run_ids": ["run_id"],
      "cited_span_ids": [],
      "suggested_change_kind": "retrieval_params|prompt_fewshot|tool_routing",
      "rationale": "变更理由",
      "diff": { "system_prompt_append": "可选追加 few-shot/负例", "retrieval": {"top_k": 5} }
    }
  ]
}
规则：
- suggested_change_kind 禁止 guardrail/audit/observability/auth
- diff 只能改 prompt 措辞/few-shot 或检索参数 top_k/similarity；不要改安全策略
- 若轨迹不足，返回空 findings 数组
"""


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"findings": []}
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {"findings": []}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {"findings": []}


def _heuristic_findings(trajectories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not trajectories:
        return []
    error_runs = [t for t in trajectories if t.get("status") == "ERROR"]
    neg_fb = [t for t in trajectories if t.get("feedback")]
    findings: List[Dict[str, Any]] = []
    if neg_fb or error_runs:
        samples = (error_runs or neg_fb)[:3]
        run_ids = [t["run_id"] for t in samples]
        summaries = "; ".join((t.get("summary") or t.get("error_code") or "")[:80] for t in samples)
        findings.append(
            {
                "failure_mode": "recurring_failure_or_negative_feedback",
                "cited_run_ids": run_ids,
                "cited_span_ids": [],
                "suggested_change_kind": "prompt_fewshot",
                "rationale": f"近期失败或负反馈样本：{summaries or '见轨迹'}",
                "diff": {
                    "system_prompt_append": (
                        "\n\n## 自优化补充（候选）\n"
                        "- 遇到相似失败场景时，先澄清关键约束再行动。\n"
                        f"- 参考失败摘要：{summaries[:200]}\n"
                    )
                },
            }
        )
    hitl = [t for t in trajectories if t.get("status") == "HITL_WAIT"]
    if hitl:
        findings.append(
            {
                "failure_mode": "frequent_hitl",
                "cited_run_ids": [t["run_id"] for t in hitl[:3]],
                "cited_span_ids": [],
                "suggested_change_kind": "tool_routing",
                "rationale": "HITL 介入偏多，建议收紧工具调用说明与审批边界描述（需人工审批后 A/B）",
                "diff": {
                    "system_prompt_append": (
                        "\n\n## 工具调用约束（候选）\n"
                        "- 高风险写操作前先总结意图并等待确认。\n"
                    )
                },
            }
        )
    return findings


async def reflect(
    db: Session,
    *,
    agent: Agent,
    trajectories: List[Dict[str, Any]],
    model_service_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not trajectories:
        return []

    from services.selfopt.config import resolve_reflect_model_service_id

    resolved_msid = resolve_reflect_model_service_id(agent, override=model_service_id)

    # Prefer LLM; fall back to heuristics
    findings: List[Dict[str, Any]] = []
    try:
        svc = (
            db.query(ModelService)
            .filter(ModelService.model_service_id == resolved_msid)
            .first()
        )
        provider = None
        if svc:
            provider = (
                db.query(ModelProvider)
                .filter(ModelProvider.provider_id == svc.provider_id)
                .first()
            )
        if svc and provider:
            payload = {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "trajectories": trajectories[:15],
                "allowed_change_kinds": [k for k, t in CHANGE_KIND_TIERS.items() if t != "FORBIDDEN"],
            }
            completion = await ModelProviderService.chat_completion(
                provider,
                svc.model_name,
                messages=[
                    {"role": "system", "content": REFLECT_SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:12000]},
                ],
                max_tokens=2048,
                temperature=0.2,
                timeout_seconds=60,
                source="selfopt_reflect",
            )
            choices = completion.get("choices") or []
            content = ""
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
            parsed = _extract_json(content)
            findings = list(parsed.get("findings") or [])
    except Exception:
        findings = []

    if not findings:
        findings = _heuristic_findings(trajectories)

    cleaned: List[Dict[str, Any]] = []
    for f in findings:
        kind = str(f.get("suggested_change_kind") or "prompt_fewshot")
        if is_forbidden_change_kind(kind):
            continue
        if kind not in CHANGE_KIND_TIERS:
            kind = "prompt_fewshot"
        f["suggested_change_kind"] = kind
        f["diff"] = f.get("diff") if isinstance(f.get("diff"), dict) else {}
        cleaned.append(f)
    return cleaned
