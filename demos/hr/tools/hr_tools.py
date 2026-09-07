"""HR demo local_python tools — read-only SQLite mock HRIS."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DATA_DIR / "demo_hr.db"
_OUTBOX = Path(__file__).resolve().parent.parent / "outbox"


def _connect() -> sqlite3.Connection:
    if not _DB_PATH.exists():
        raise FileNotFoundError(
            f"HR demo DB not found: {_DB_PATH}. Run seed_demo.py first."
        )
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def _strip_comp(row: Dict[str, Any], include_compensation: bool) -> Dict[str, Any]:
    out = dict(row)
    if not include_compensation:
        out.pop("salary_band", None)
    return out


def hr_search_employees(
    department: Optional[str] = None,
    level: Optional[str] = None,
    name: Optional[str] = None,
    include_compensation: bool = False,
) -> Dict[str, Any]:
    """Search employees by department name, level, or name."""
    sql = (
        "SELECT e.*, d.name AS department_name FROM employees e "
        "JOIN departments d ON e.dept_id = d.dept_id WHERE 1=1"
    )
    params: List[Any] = []
    if department:
        sql += " AND d.name LIKE ?"
        params.append(f"%{department}%")
    if level:
        sql += " AND e.level = ?"
        params.append(level)
    if name:
        sql += " AND e.name LIKE ?"
        params.append(f"%{name}%")
    sql += " ORDER BY e.hire_date"
    with _connect() as conn:
        rows = [_strip_comp(r, include_compensation) for r in _rows(conn.execute(sql, params))]
    return {"success": True, "count": len(rows), "employees": rows}


def hr_get_employee(
    emp_id: Optional[str] = None,
    name: Optional[str] = None,
    include_compensation: bool = False,
) -> Dict[str, Any]:
    """Get one employee; salary_band omitted unless include_compensation=true."""
    with _connect() as conn:
        if emp_id:
            cur = conn.execute(
                "SELECT e.*, d.name AS department_name FROM employees e "
                "JOIN departments d ON e.dept_id = d.dept_id WHERE e.emp_id = ?",
                (emp_id,),
            )
        elif name:
            cur = conn.execute(
                "SELECT e.*, d.name AS department_name FROM employees e "
                "JOIN departments d ON e.dept_id = d.dept_id WHERE e.name LIKE ?",
                (f"%{name}%",),
            )
        else:
            return {"success": False, "error": "emp_id 或 name 必填"}
        rows = [_strip_comp(r, include_compensation) for r in _rows(cur)]
    return {"success": True, "count": len(rows), "employees": rows}


def hr_get_leave_balance(
    department: Optional[str] = None,
    top_n: int = 3,
    leave_type: str = "annual",
) -> Dict[str, Any]:
    """Top-N remaining leave balances, optionally filtered by department name."""
    top_n = max(1, min(int(top_n), 20))
    col = "annual_remaining" if leave_type != "compensatory" else "compensatory_remaining"
    sql = (
        f"SELECT e.emp_id, e.name, d.name AS department_name, e.title, "
        f"lb.annual_remaining, lb.compensatory_remaining, lb.as_of "
        f"FROM leave_balances lb "
        f"JOIN employees e ON e.emp_id = lb.emp_id "
        f"JOIN departments d ON e.dept_id = d.dept_id "
    )
    params: List[Any] = []
    if department:
        sql += "WHERE d.name LIKE ? "
        params.append(f"%{department}%")
    sql += f"ORDER BY lb.{col} DESC LIMIT ?"
    params.append(top_n)
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {
        "success": True,
        "leave_type": leave_type,
        "department": department,
        "top_n": top_n,
        "items": rows,
    }


def hr_list_open_requisitions(department: Optional[str] = None) -> Dict[str, Any]:
    """List open job requisitions."""
    sql = (
        "SELECT r.*, d.name AS department_name FROM job_requisitions r "
        "JOIN departments d ON r.dept_id = d.dept_id WHERE r.status = 'open'"
    )
    params: List[Any] = []
    if department:
        sql += " AND d.name LIKE ?"
        params.append(f"%{department}%")
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "requisitions": rows}


def hr_get_candidate(name: Optional[str] = None, candidate_id: Optional[str] = None) -> Dict[str, Any]:
    """Get candidate profile and interview rounds."""
    with _connect() as conn:
        if candidate_id:
            cur = conn.execute("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,))
        elif name:
            cur = conn.execute("SELECT * FROM candidates WHERE name LIKE ?", (f"%{name}%",))
        else:
            return {"success": False, "error": "name 或 candidate_id 必填"}
        cands = _rows(cur)
        for c in cands:
            iv = _rows(
                conn.execute(
                    "SELECT * FROM interviews WHERE candidate_id = ? ORDER BY interview_id",
                    (c["candidate_id"],),
                )
            )
            c["interviews"] = iv
            if c.get("req_id"):
                req = conn.execute(
                    "SELECT * FROM job_requisitions WHERE req_id = ?", (c["req_id"],)
                ).fetchone()
                c["requisition"] = dict(req) if req else None
    return {"success": True, "count": len(cands), "candidates": cands}


def hr_create_interview_note(
    candidate_name: str,
    round_name: str,
    note_markdown: str,
) -> Dict[str, Any]:
    """Write interview note to outbox (may require HITL)."""
    _OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in candidate_name)[:32]
    path = _OUTBOX / f"{ts}_{safe}_{round_name}.md"
    path.write_text(
        f"# 面试纪要 · {candidate_name} · {round_name}\n\n{note_markdown}\n",
        encoding="utf-8",
    )
    return {
        "success": True,
        "status": "pending_approval",
        "outbox_path": str(path),
        "message": "面试纪要已写入 outbox，等待确认。",
    }


if __name__ == "__main__":
    print(json.dumps(hr_get_leave_balance(department="研发"), ensure_ascii=False, indent=2))
