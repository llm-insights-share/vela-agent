"""Audit demo local_python tools — read-only SQLite mock OA / finance."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DATA_DIR / "demo_audit.db"
_OUTBOX = Path(__file__).resolve().parent.parent / "outbox"


def _connect() -> sqlite3.Connection:
    if not _DB_PATH.exists():
        raise FileNotFoundError(
            f"Audit demo DB not found: {_DB_PATH}. Run seed_demo.py first."
        )
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def audit_lookup_employee(
    name: Optional[str] = None,
    emp_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Lookup auditee employee profile by name or emp_id."""
    if not name and not emp_id:
        return {"success": False, "error": "name 或 emp_id 至少提供一个"}
    with _connect() as conn:
        if emp_id:
            cur = conn.execute(
                "SELECT * FROM employees WHERE emp_id = ?", (emp_id,)
            )
        else:
            cur = conn.execute(
                "SELECT * FROM employees WHERE name LIKE ?", (f"%{name}%",)
            )
        rows = _rows(cur)
    return {"success": True, "count": len(rows), "employees": rows}


def audit_list_oa_docs(
    emp_id: str,
    doc_type: Optional[str] = None,
) -> Dict[str, Any]:
    """List OA archive documents for an employee."""
    with _connect() as conn:
        if doc_type:
            cur = conn.execute(
                "SELECT * FROM oa_archives WHERE emp_id = ? AND doc_type = ? ORDER BY filed_at",
                (emp_id, doc_type),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM oa_archives WHERE emp_id = ? ORDER BY filed_at",
                (emp_id,),
            )
        rows = _rows(cur)
    return {"success": True, "emp_id": emp_id, "count": len(rows), "documents": rows}


def audit_query_gl(
    org_id: str,
    period_from: str,
    period_to: str,
    account_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Query GL balances for an org within period range (inclusive, YYYY-MM)."""
    with _connect() as conn:
        sql = (
            "SELECT * FROM gl_balances WHERE org_id = ? "
            "AND period >= ? AND period <= ?"
        )
        params: List[Any] = [org_id, period_from, period_to]
        if account_code:
            sql += " AND account_code = ?"
            params.append(account_code)
        sql += " ORDER BY period, account_code"
        cur = conn.execute(sql, params)
        rows = _rows(cur)
    totals: Dict[str, Dict[str, float]] = {}
    for r in rows:
        code = r["account_code"]
        bucket = totals.setdefault(code, {"debit": 0.0, "credit": 0.0, "account_name": r["account_name"]})
        bucket["debit"] += float(r["debit"])
        bucket["credit"] += float(r["credit"])
    return {
        "success": True,
        "org_id": org_id,
        "period_from": period_from,
        "period_to": period_to,
        "rows": rows,
        "account_totals": totals,
    }


def audit_query_related_party(
    org_id: str,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    """Query AR/AP focusing on related-party and aging anomalies."""
    with _connect() as conn:
        if period:
            cur = conn.execute(
                "SELECT * FROM ap_ar WHERE org_id = ? AND period = ? ORDER BY related_party DESC, aging_days DESC",
                (org_id, period),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM ap_ar WHERE org_id = ? ORDER BY related_party DESC, aging_days DESC",
                (org_id,),
            )
        rows = _rows(cur)
    anomalies = [
        r
        for r in rows
        if int(r.get("related_party") or 0) == 1 and int(r.get("aging_days") or 0) > 180
    ]
    return {
        "success": True,
        "org_id": org_id,
        "period": period,
        "items": rows,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
    }


def audit_list_contracts(
    org_id: str,
    min_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """List major contracts; flag missing approval_no."""
    with _connect() as conn:
        if min_amount is not None:
            cur = conn.execute(
                "SELECT * FROM contracts WHERE org_id = ? AND amount >= ? ORDER BY amount DESC",
                (org_id, float(min_amount)),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM contracts WHERE org_id = ? ORDER BY amount DESC",
                (org_id,),
            )
        rows = _rows(cur)
    missing_approval = [r for r in rows if not r.get("approval_no")]
    return {
        "success": True,
        "org_id": org_id,
        "contracts": rows,
        "missing_approval": missing_approval,
        "count": len(rows),
    }


def audit_list_capex(org_id: str) -> Dict[str, Any]:
    """List capex projects and over-budget flags."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT *, CASE WHEN budget > 0 THEN actual * 1.0 / budget ELSE NULL END AS spend_ratio "
            "FROM capex WHERE org_id = ? ORDER BY risk_flag DESC, actual DESC",
            (org_id,),
        )
        rows = _rows(cur)
    return {"success": True, "org_id": org_id, "projects": rows, "count": len(rows)}


def audit_submit_engagement_draft(
    title: str,
    markdown_body: str,
) -> Dict[str, Any]:
    """Write engagement draft to outbox (HITL / pending approval)."""
    _OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:64] or "draft"
    path = _OUTBOX / f"{ts}_{safe}.md"
    path.write_text(f"# {title}\n\n{markdown_body}\n", encoding="utf-8")
    return {
        "success": True,
        "status": "pending_approval",
        "title": title,
        "outbox_path": str(path),
        "message": "立项草案已写入 outbox，等待人工审批。",
    }


# CLI smoke test
if __name__ == "__main__":
    print(json.dumps(audit_lookup_employee(name="张伟"), ensure_ascii=False, indent=2))
