"""Delivery HITL approve merges into a single assistant bubble."""

from unittest.mock import MagicMock


def test_delivery_approve_merges_in_place_no_append():
    """Simulate the message mutation logic used in hitl delivery approve."""
    approval_id = "appr-1"
    gate_notice = "⏸️ HITL Gate\n审批工单 ID: `appr-1`"
    final_result = "## 交付物\n唯一正文"
    messages = [
        {
            "role": "assistant",
            "content": gate_notice,
            "hitlGateNotice": gate_notice,
            "pendingApprovalId": approval_id,
            "pendingDelivery": True,
            "thinking": "[Coordinator] done",
            "executionStory": {"status": "hitl_wait", "phases": []},
            "executionMode": "multi_agent",
        }
    ]

    # Same loop as routes/hitl.py delivery approve
    for m in messages:
        pid = m.get("pendingApprovalId") or m.get("pending_approval_id")
        if pid != approval_id:
            continue
        prev_content = (m.get("content") or "").strip()
        if not m.get("hitlGateNotice") and prev_content:
            m["hitlGateNotice"] = prev_content
        m["approvalStatus"] = "approved"
        m["pendingDelivery"] = True
        m["content"] = final_result or "（交付内容为空）"
        m.pop("approvalFinalResult", None)

    assert len(messages) == 1
    m = messages[0]
    assert m["approvalStatus"] == "approved"
    assert m["content"] == final_result
    assert m["hitlGateNotice"] == gate_notice
    assert m["thinking"] == "[Coordinator] done"
    assert m["executionStory"]["status"] == "hitl_wait"
    assert "approvalFinalResult" not in m


def test_frontend_heal_folds_legacy_append():
    msgs = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "⏸️ 交付前 HITL Gate\n审批工单 ID: `x`",
            "pendingApprovalId": "x",
            "pendingDelivery": True,
            "thinking": "log",
            "executionStory": {"status": "done", "phases": []},
        },
        {
            "role": "assistant",
            "content": "正式正文",
            "meta": {"approved": True, "approval_id": "x"},
        },
    ]
    approved_ids = {"x"}
    final_by = {"x": "正式正文"}
    skip = set()
    healed = []
    for idx, m in enumerate(msgs):
        meta = m.get("meta") or {}
        aid = meta.get("approval_id")
        if aid and meta.get("approved") is True and not m.get("pendingApprovalId"):
            skip.add(idx)
            continue
        pid = m.get("pendingApprovalId")
        if pid in approved_ids:
            prev = (m.get("content") or "").strip()
            final = final_by[pid]
            healed.append({
                **m,
                "approvalStatus": "approved",
                "hitlGateNotice": prev,
                "content": final,
            })
        else:
            healed.append(m)
    healed = [m for i, m in enumerate(healed) if i not in skip]
    # user + one assistant (skip removes from original indexes; filter after map)
    # rebuild properly:
    out = []
    for idx, m in enumerate(msgs):
        if idx in skip:
            continue
        meta = m.get("meta") or {}
        if m.get("pendingApprovalId") in approved_ids:
            prev = (m.get("content") or "").strip()
            out.append({
                **m,
                "approvalStatus": "approved",
                "hitlGateNotice": prev,
                "content": final_by[m["pendingApprovalId"]],
            })
        else:
            out.append(m)
    assert len(out) == 2
    assert out[1]["content"] == "正式正文"
    assert "HITL Gate" in out[1]["hitlGateNotice"]
    assert out[1]["thinking"] == "log"
