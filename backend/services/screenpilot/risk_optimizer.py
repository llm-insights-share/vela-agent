"""基于审计样本的风险策略自动优化建议。"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from models import UiAuditLog


def analyze_audit_samples(db: Session, *, limit: int = 500) -> Dict[str, Any]:
    """分析最近审计日志，生成 risk_rules 调优建议。"""
    rows = (
        db.query(UiAuditLog)
        .order_by(UiAuditLog.created_at.desc())
        .limit(min(limit, 2000))
        .all()
    )
    if not rows:
        return {"sample_count": 0, "suggestions": [], "stats": {}}

    tier_counts = Counter(r.risk_tier for r in rows)
    hitl_actions = Counter()
    label_tiers: Dict[str, Counter] = defaultdict(Counter)

    for r in rows:
        payload = r.payload or {}
        label = (payload.get("target_label") or "").strip()
        if r.action.startswith("hitl_gate:"):
            hitl_actions[r.action.replace("hitl_gate:", "")] += 1
        if label:
            label_tiers[label][r.risk_tier] += 1

    suggestions: List[Dict[str, Any]] = []

    # T1 click 频繁触发 HITL 驳回 → 建议降级关键词
    for label, tiers in label_tiers.items():
        total = sum(tiers.values())
        t2t3 = tiers.get("T2", 0) + tiers.get("T3", 0)
        if total >= 5 and t2t3 / total < 0.1:
            suggestions.append({
                "type": "relax_t2",
                "label": label,
                "reason": f"标签「{label}」{total} 次操作中仅 {t2t3} 次 T2/T3，可考虑从 T2 关键词移除",
                "confidence": min(0.9, 0.5 + total * 0.05),
            })

    # 高频 T3 标签未在默认关键词 → 建议加入 t3_labels
    for label, tiers in label_tiers.items():
        if tiers.get("T3", 0) >= 3:
            suggestions.append({
                "type": "add_t3_label",
                "label": label,
                "reason": f"标签「{label}」出现 {tiers['T3']} 次 T3 审计，建议加入 risk_rules.t3_labels",
                "confidence": min(0.95, 0.6 + tiers["T3"] * 0.1),
            })

    # 提交类动作 T1 过多 → 建议加强
    submit_like = sum(
        1 for r in rows
        if r.risk_tier == "T1"
        and "提交" in str((r.payload or {}).get("target_label", ""))
    )
    if submit_like >= 3:
        suggestions.append({
            "type": "tighten_submit",
            "reason": f"检测到 {submit_like} 次「提交」类动作为 T1，建议复核 risk_rules",
            "confidence": 0.75,
        })

    return {
        "sample_count": len(rows),
        "stats": {
            "tier_counts": dict(tier_counts),
            "hitl_gate_actions": dict(hitl_actions),
            "unique_labels": len(label_tiers),
        },
        "suggestions": sorted(suggestions, key=lambda x: -x.get("confidence", 0)),
    }


def apply_suggestions_to_rules(
    current_rules: Dict[str, Any],
    suggestions: List[Dict[str, Any]],
    *,
    min_confidence: float = 0.7,
) -> Dict[str, Any]:
    """将高置信度建议合并到 risk_rules（仅追加，不删除现有规则）。"""
    rules = dict(current_rules or {})
    t3_labels = list(rules.get("t3_labels") or [])

    for s in suggestions:
        if s.get("confidence", 0) < min_confidence:
            continue
        if s.get("type") == "add_t3_label":
            label = s.get("label", "")
            if label and label not in t3_labels:
                t3_labels.append(label)

    if t3_labels:
        rules["t3_labels"] = t3_labels
    rules["last_optimized"] = True
    return rules
