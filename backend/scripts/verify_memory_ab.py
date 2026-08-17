#!/usr/bin/env python3
"""Memory A/B verification: no-memory vs with-memory agent correctness.

Design goals:
  - Seed *unique* facts the base LLM cannot know a priori
  - Ask questions that require those facts
  - Compare answers with memory_enabled=False vs True
  - Score by required keyword / pattern hits

Usage (backend running + Letta healthy):
  cd backend
  .venv/bin/python scripts/verify_memory_ab.py

Writes:
  ../docs/memory-ab-verification-report.md
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
REPORT_PATH = REPO / "docs" / "memory-ab-verification-report.md"

BASE = os.environ.get("VELA_BASE", "http://127.0.0.1:8000/api/v1")
USER = os.environ.get("VELA_USER", "admin")
PASSWORD = os.environ.get("VELA_PASSWORD", "admin123")
# Prefer demo1 (memory already used in prior work); override with VELA_AGENT_ID
DEFAULT_AGENT = os.environ.get("VELA_AGENT_ID", "341b3b4f-a994-40f3-8f95-4c0d0f4e09e2")
VERIFY_USER = "memory-ab-verify"


@dataclass
class TestCase:
    id: str
    category: str
    description: str
    seed_kind: str  # block | passage
    seed_payload: Dict[str, Any]
    question: str
    must_contain: List[str]  # all should appear when memory ON
    must_not_guess: List[str] = field(default_factory=list)  # unique tokens unlikely without memory
    weight: float = 1.0


@dataclass
class CaseResult:
    case_id: str
    category: str
    description: str
    question: str
    answer_off: str
    answer_on: str
    score_off: float
    score_on: float
    hits_off: List[str]
    hits_on: List[str]
    improved: bool
    notes: str = ""


# Unique tokens — not in general LLM training as "this user's preference"
CASES: List[TestCase] = [
    TestCase(
        id="TC-PREF-01",
        category="核心记忆-用户偏好",
        description="用户偏好：报告必须用特定密语开头",
        seed_kind="block",
        seed_payload={
            "label": "user_pref",
            "value": (
                "【验证用偏好】该用户要求：所有书面报告必须以『密语：蓝莓派-9917』作为第一行；"
                "正文使用 Markdown；结尾必须附『风险清单』小节。"
            ),
        },
        question="请按我的偏好写一段极短的周报开头（只要前几行即可）。不要解释，直接输出。",
        must_contain=["蓝莓派-9917"],
        must_not_guess=["蓝莓派-9917"],
        weight=1.5,
    ),
    TestCase(
        id="TC-ARCH-01",
        category="归档记忆-经验召回",
        description="归档经验：历史项目结论代号",
        seed_kind="passage",
        seed_payload={
            "text": (
                "历史经验：审计项目『星河专项』最终结论代号为 ORBIT-7742，"
                "关键风险为供应商集中度过高，整改责任人是王砺。"
            ),
            "tags": ["experience", "ab-verify", "orbit"],
        },
        question="星河专项的最终结论代号是什么？只回答代号，不要解释。",
        must_contain=["ORBIT-7742"],
        must_not_guess=["ORBIT-7742"],
        weight=1.5,
    ),
    TestCase(
        id="TC-ARCH-03",
        category="归档记忆-语义检索",
        description="语义相近提问应召回不同表述的事实",
        seed_kind="passage",
        seed_payload={
            "text": (
                "客户对发票校验规则：金额偏差容忍度为 0.37%（代号 TOL-037），"
                "超过则自动驳回并通知财务组『琥珀组』。"
            ),
            "tags": ["experience", "ab-verify", "invoice"],
        },
        question="发票金额允许的偏差比例代号是什么？通知哪个组？请简短回答。",
        must_contain=["TOL-037", "琥珀组"],
        must_not_guess=["TOL-037", "琥珀组"],
        weight=1.3,
    ),
]


def _score(answer: str, must_contain: List[str]) -> tuple[float, List[str]]:
    text = answer or ""
    hits = [k for k in must_contain if k and k in text]
    if not must_contain:
        return 0.0, []
    return len(hits) / len(must_contain), hits


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=httpx.Timeout(360.0, connect=30.0))
        self.token = ""

    def login(self) -> None:
        r = self.http.post(
            f"{self.base}/auth/login",
            data={"username": USER, "password": PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def _h(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, **kw):
        return self.http.get(f"{self.base}{path}", headers=self._h(), **kw)

    def post(self, path: str, **kw):
        return self.http.post(f"{self.base}{path}", headers=self._h(), **kw)

    def put(self, path: str, **kw):
        return self.http.put(f"{self.base}{path}", headers=self._h(), **kw)

    def delete(self, path: str, **kw):
        return self.http.delete(f"{self.base}{path}", headers=self._h(), **kw)


def set_memory_enabled(c: Client, agent_id: str, enabled: bool) -> None:
    r = c.put("/config/memory/agents", json={"items": [{"agent_id": agent_id, "memory_enabled": enabled}]})
    r.raise_for_status()


def seed_case(c: Client, agent_id: str, case: TestCase) -> None:
    if case.seed_kind == "block":
        label = case.seed_payload["label"]
        value = case.seed_payload["value"]
        r = c.put(
            f"/memory/blocks/{label}",
            json={"agent_id": agent_id, "user_id": VERIFY_USER, "value": value},
        )
        r.raise_for_status()
    elif case.seed_kind == "passage":
        r = c.post(
            "/memory/passages",
            json={
                "agent_id": agent_id,
                "user_id": VERIFY_USER,
                "text": case.seed_payload["text"],
                "tags": case.seed_payload.get("tags") or ["ab-verify"],
            },
        )
        r.raise_for_status()
    else:
        raise ValueError(case.seed_kind)


def clear_verify_seeds(c: Client, agent_id: str) -> None:
    """Best-effort: clear verify blocks and ab-verify passages."""
    for label in ("user_pref", "task_context", "tool_profile"):
        try:
            c.put(
                f"/memory/blocks/{label}",
                json={"agent_id": agent_id, "user_id": VERIFY_USER, "value": ""},
            )
        except Exception:
            pass
    try:
        r = c.get(
            "/memory/passages",
            params={"agent_id": agent_id, "user_id": VERIFY_USER, "page": 1, "page_size": 100},
        )
        if r.status_code == 200:
            for item in (r.json().get("items") or []):
                c.delete(
                    f"/memory/passages/{item['id']}",
                    params={"agent_id": agent_id, "user_id": VERIFY_USER},
                )
    except Exception as e:
        print(f"[warn] clear passages: {e}")


def chat_once(c: Client, agent_id: str, question: str) -> str:
    r = c.post(
        "/sessions",
        json={"agent_id": agent_id, "caller_type": "user", "caller_id": VERIFY_USER},
    )
    r.raise_for_status()
    sid = r.json()["session_id"]
    try:
        try:
            cr = c.post(
                f"/sessions/{sid}/chat",
                json={
                    "message": question,
                    "execution_mode": "direct",
                    "skip_history": True,
                    "timeout_seconds": 240,
                },
            )
        except httpx.TimeoutException as e:
            return f"[TIMEOUT] {e}"
        if cr.status_code >= 400:
            return f"[HTTP {cr.status_code}] {cr.text[:500]}"
        data = cr.json()
        for key in ("reply", "content", "answer", "message", "result"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key]
        if isinstance(data.get("messages"), list) and data["messages"]:
            last = data["messages"][-1]
            if isinstance(last, dict):
                return str(last.get("content") or last.get("text") or "")
        return json.dumps(data, ensure_ascii=False)[:2000]
    finally:
        # 不 close：避免 MemoryProcessor 蒸馏把错误回答写回 Letta 污染后续用例
        pass


def probe_recall(c: Client, agent_id: str, query: str) -> List[Dict[str, Any]]:
    r = c.get(
        "/memory/passages",
        params={
            "agent_id": agent_id,
            "user_id": VERIFY_USER,
            "query": query,
            "page": 1,
            "page_size": 5,
        },
    )
    if r.status_code != 200:
        return []
    return r.json().get("items") or []


def run_infra_checks(c: Client) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    h = c.get("/memory/letta/status")
    out["letta_status"] = h.json() if h.status_code == 200 else {"error": h.text}
    out["health"] = c.get("/health").json() if hasattr(c, "get") else {}
    try:
        out["health"] = httpx.get(f"{BASE.rsplit('/api/v1', 1)[0]}/api/v1/health", timeout=5).json()
    except Exception as e:
        out["health"] = {"error": str(e)}
    return out


def run_retrieval_layer(c: Client, agent_id: str) -> List[Dict[str, Any]]:
    """No-LLM checks: seeded facts are readable / searchable."""
    rows = []
    clear_verify_seeds(c, agent_id)
    for case in CASES:
        seed_case(c, agent_id, case)
        time.sleep(0.2)
        ok = False
        detail = ""
        if case.seed_kind == "block":
            r = c.get(
                "/memory/blocks",
                params={"agent_id": agent_id, "user_id": VERIFY_USER},
            )
            blocks = r.json() if r.status_code == 200 else []
            blob = " ".join((b.get("value") or "") for b in blocks)
            hits = [k for k in case.must_contain if k in blob]
            ok = len(hits) == len(case.must_contain)
            detail = f"block_hits={hits}"
        else:
            items = probe_recall(c, agent_id, case.question)
            blob = " ".join((i.get("content") or i.get("text") or "") for i in items)
            hits = [k for k in case.must_contain if k in blob]
            ok = len(hits) >= 1  # at least one keyword recalled
            detail = f"semantic_hits={len(items)} keyword_hits={hits}"
        rows.append({"case_id": case.id, "ok": ok, "detail": detail})
        print(f"  retrieval {case.id}: ok={ok} {detail}")
    return rows


def run_ab(c: Client, agent_id: str) -> List[CaseResult]:
    results: List[CaseResult] = []
    print(f"Clearing previous verify seeds for {VERIFY_USER}...")
    clear_verify_seeds(c, agent_id)

    for case in CASES:
        print(f"\n=== {case.id} {case.description} ===")
        seed_case(c, agent_id, case)
        time.sleep(0.3)

        recall_note = ""
        if case.seed_kind == "passage":
            hits = probe_recall(c, agent_id, case.question)
            recall_note = f"semantic_hits={len(hits)}"
            print(f"  recall: {recall_note}")

        set_memory_enabled(c, agent_id, False)
        time.sleep(0.2)
        print("  chat memory=OFF ...")
        ans_off = chat_once(c, agent_id, case.question)
        score_off, hits_off = _score(ans_off, case.must_contain)

        set_memory_enabled(c, agent_id, True)
        time.sleep(0.2)
        print("  chat memory=ON ...")
        ans_on = chat_once(c, agent_id, case.question)
        score_on, hits_on = _score(ans_on, case.must_contain)

        improved = score_on > score_off + 1e-9
        print(f"  score_off={score_off:.2f} hits={hits_off}")
        print(f"  score_on ={score_on:.2f} hits={hits_on} improved={improved}")
        print(f"  off[:120]={ans_off[:120]!r}")
        print(f"  on[:120]={ans_on[:120]!r}")

        results.append(
            CaseResult(
                case_id=case.id,
                category=case.category,
                description=case.description,
                question=case.question,
                answer_off=ans_off[:800],
                answer_on=ans_on[:800],
                score_off=score_off,
                score_on=score_on,
                hits_off=hits_off,
                hits_on=hits_on,
                improved=improved,
                notes=recall_note,
            )
        )

    set_memory_enabled(c, agent_id, True)
    return results


def weighted_summary(results: List[CaseResult]) -> Dict[str, Any]:
    by_id = {c.id: c for c in CASES}
    w_off = w_on = 0.0
    tw = 0.0
    improved_n = 0
    for r in results:
        w = by_id[r.case_id].weight
        tw += w
        w_off += r.score_off * w
        w_on += r.score_on * w
        if r.improved:
            improved_n += 1
    return {
        "cases": len(results),
        "improved_cases": improved_n,
        "weighted_score_off": round(w_off / tw, 4) if tw else 0,
        "weighted_score_on": round(w_on / tw, 4) if tw else 0,
        "delta": round((w_on - w_off) / tw, 4) if tw else 0,
    }


def render_report(
    agent_id: str,
    infra: Dict[str, Any],
    results: List[CaseResult],
    summary: Dict[str, Any],
    elapsed_s: float,
    retrieval_rows: Optional[List[Dict[str, Any]]] = None,
) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "# 记忆模块 A/B 验证报告",
        "",
        f"- 生成时间：{now}",
        f"- Agent：`{agent_id}`",
        f"- 验证用户作用域：`{VERIFY_USER}`",
        f"- 耗时：{elapsed_s:.1f}s",
        f"- Letta：`{json.dumps(infra.get('letta_status'), ensure_ascii=False)}`",
        "",
        "## 1. 测试目标",
        "",
        "验证开启 Letta 记忆（核心 blocks + 归档语义召回）后，Agent 对**仅存在于记忆中的用户偏好/历史经验**的回答正确率，是否高于关闭记忆时。",
        "",
        "## 2. 方法",
        "",
        "1. 向指定 `(agent, user)` 作用域写入唯一密语事实（LLM 预训练不可能准确猜中）。",
        "2. **检索层**：检查 blocks/passages 是否可读、语义检索是否命中（不经过对话模型）。",
        "3. **对照组** `memory_enabled=false`：同问题新开会话提问。",
        "4. **实验组** `memory_enabled=true`：同问题新开会话提问。",
        "5. 评分：答案命中必含关键词比例（0~1）；加权汇总。",
        "",
        "## 3. 测试用例设计",
        "",
        "| ID | 类别 | 说明 | 必含关键词 | 权重 |",
        "|----|------|------|------------|------|",
    ]
    for c in CASES:
        lines.append(
            f"| {c.id} | {c.category} | {c.description} | `{', '.join(c.must_contain)}` | {c.weight} |"
        )

    if retrieval_rows is not None:
        ok_n = sum(1 for r in retrieval_rows if r.get("ok"))
        lines += [
            "",
            "## 4. 检索层结果（无 LLM）",
            "",
            f"通过率：{ok_n}/{len(retrieval_rows)}",
            "",
            "| Case | 通过 | 细节 |",
            "|------|------|------|",
        ]
        for r in retrieval_rows:
            lines.append(f"| {r['case_id']} | {'是' if r['ok'] else '否'} | {r['detail']} |")

    lines += [
        "",
        "## 5. 对话层 A/B 结果",
        "",
        f"| 指标 | 无记忆 | 有记忆 | Δ |",
        f"|------|--------|--------|---|",
        f"| 加权正确率 | {summary['weighted_score_off']:.2%} | {summary['weighted_score_on']:.2%} | {summary['delta']:+.2%} |",
        f"| 有提升用例数 | — | {summary['improved_cases']}/{summary['cases']} | — |",
        "",
    ]

    conclusion = (
        "开启记忆后加权正确率明显提升，说明记忆召回能提升对个性化事实的回答正确性。"
        if summary["delta"] >= 0.3
        else (
            "开启记忆后有一定提升，但仍有用例未完全命中，需检查召回/注入链路或模型遵从度。"
            if summary["delta"] > 0
            else "开启记忆后未观察到提升，需排查 Letta 召回、AgentLoop 注入或模型忽略上下文等问题。"
        )
    )
    lines += ["## 6. 结论", "", conclusion, ""]

    lines += ["## 7. 分用例明细（对话）", ""]
    for r in results:
        lines += [
            f"### {r.case_id} — {r.description}",
            "",
            f"- 类别：{r.category}",
            f"- 问题：{r.question}",
            f"- 无记忆得分：{r.score_off:.2f}（命中 {r.hits_off or '无'}）",
            f"- 有记忆得分：{r.score_on:.2f}（命中 {r.hits_on or '无'}）",
            f"- 是否提升：{'是' if r.improved else '否'}",
            f"- 备注：{r.notes or '—'}",
            "",
            "<details><summary>无记忆回答</summary>",
            "",
            "```",
            r.answer_off or "(空)",
            "```",
            "",
            "</details>",
            "",
            "<details><summary>有记忆回答</summary>",
            "",
            "```",
            r.answer_on or "(空)",
            "```",
            "",
            "</details>",
            "",
        ]

    lines += [
        "## 8. 补充基础设施用例（清单）",
        "",
        "| ID | 场景 | 期望 |",
        "|----|------|------|",
        "| TC-INFRA-01 | Letta `/memory/letta/status` | healthy=true, embedding_dim=1024 |",
        "| TC-INFRA-02 | 网关 `/llm-gateway/v1/embeddings` | 返回 1024 维向量 |",
        "| TC-INFRA-03 | 记忆管理 page_size≤100 | 页面可打开、Agent 列表正常 |",
        "| TC-INFRA-04 | Letta 停机 fail-open | 聊天仍 200，记忆降级 |",
        "| TC-INFRA-05 | 会话关闭蒸馏 | blocks/passages 更新（需真实多轮会话） |",
        "",
        "本报告主实验覆盖 TC-PREF / TC-ARCH；基础设施项可在运维巡检中复验。",
        "",
        "## 9. 复现命令",
        "",
        "```bash",
        "cd backend",
        ".venv/bin/python scripts/verify_memory_ab.py",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    agent_id = DEFAULT_AGENT
    c = Client(BASE)
    print("Login...")
    c.login()
    infra = {"letta_status": c.get("/memory/letta/status").json()}
    print("Letta:", infra["letta_status"])
    if not infra["letta_status"].get("healthy"):
        print("ERROR: Letta unhealthy; abort")
        return 2

    ar = c.get(f"/agents/{agent_id}")
    if ar.status_code != 200:
        print(f"ERROR: agent {agent_id} not found")
        return 2
    print("Agent:", ar.json().get("name"), agent_id)

    t0 = time.time()
    print("\n--- Retrieval layer ---")
    retrieval_rows = run_retrieval_layer(c, agent_id)
    print("\n--- Chat A/B layer ---")
    results = run_ab(c, agent_id)
    elapsed = time.time() - t0
    summary = weighted_summary(results)
    report = render_report(agent_id, infra, results, summary, elapsed, retrieval_rows)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report written: {REPORT_PATH}")
    # Success if retrieval mostly ok OR chat delta > 0
    ret_ok = sum(1 for r in retrieval_rows if r["ok"])
    if ret_ok == len(retrieval_rows) and summary["delta"] >= 0:
        return 0
    if summary["delta"] > 0:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
