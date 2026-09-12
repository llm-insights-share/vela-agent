"""Office demo local_python tools — OA / admin mock SQLite."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DATA_DIR / "demo_office.db"
_OUTBOX = Path(__file__).resolve().parent.parent / "outbox"


def _connect() -> sqlite3.Connection:
    if not _DB_PATH.exists():
        raise FileNotFoundError(
            f"Office demo DB not found: {_DB_PATH}. Run seed_demo.py first."
        )
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def office_search_employees(name: Optional[str] = None, dept: Optional[str] = None) -> Dict[str, Any]:
    sql = "SELECT * FROM employees WHERE 1=1"
    params: List[Any] = []
    if name:
        sql += " AND name LIKE ?"
        params.append(f"%{name}%")
    if dept:
        sql += " AND dept LIKE ?"
        params.append(f"%{dept}%")
    sql += " ORDER BY emp_id"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "employees": rows}


def office_list_rooms(status: Optional[str] = None) -> Dict[str, Any]:
    sql = "SELECT * FROM meeting_rooms WHERE 1=1"
    params: List[Any] = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "rooms": rows}


def office_list_meetings(
    status: Optional[str] = None,
    organizer_name: Optional[str] = None,
    date_from: Optional[str] = None,
) -> Dict[str, Any]:
    sql = (
        "SELECT m.*, e.name AS organizer_name, r.name AS room_name "
        "FROM meetings m "
        "JOIN employees e ON m.organizer_id = e.emp_id "
        "LEFT JOIN meeting_rooms r ON m.room_id = r.room_id WHERE 1=1"
    )
    params: List[Any] = []
    if status:
        sql += " AND m.status = ?"
        params.append(status)
    if organizer_name:
        sql += " AND e.name LIKE ?"
        params.append(f"%{organizer_name}%")
    if date_from:
        sql += " AND m.start_at >= ?"
        params.append(date_from)
    sql += " ORDER BY m.start_at"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "meetings": rows}


def office_get_meeting(meeting_id: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
    with _connect() as conn:
        if meeting_id:
            cur = conn.execute(
                "SELECT m.*, e.name AS organizer_name, r.name AS room_name "
                "FROM meetings m JOIN employees e ON m.organizer_id = e.emp_id "
                "LEFT JOIN meeting_rooms r ON m.room_id = r.room_id WHERE m.meeting_id = ?",
                (meeting_id,),
            )
        elif title:
            cur = conn.execute(
                "SELECT m.*, e.name AS organizer_name, r.name AS room_name "
                "FROM meetings m JOIN employees e ON m.organizer_id = e.emp_id "
                "LEFT JOIN meeting_rooms r ON m.room_id = r.room_id WHERE m.title LIKE ?",
                (f"%{title}%",),
            )
        else:
            return {"success": False, "error": "meeting_id 或 title 必填"}
        meetings = _rows(cur)
        for m in meetings:
            m["minutes"] = _rows(
                conn.execute(
                    "SELECT * FROM meeting_minutes WHERE meeting_id = ?",
                    (m["meeting_id"],),
                )
            )
            m["actions"] = _rows(
                conn.execute(
                    "SELECT a.*, e.name AS owner_name FROM action_items a "
                    "JOIN employees e ON a.owner_id = e.emp_id WHERE a.meeting_id = ?",
                    (m["meeting_id"],),
                )
            )
    return {"success": True, "count": len(meetings), "meetings": meetings}


def office_list_action_items(
    status: Optional[str] = None,
    owner_name: Optional[str] = None,
    overdue_only: bool = False,
) -> Dict[str, Any]:
    sql = (
        "SELECT a.*, e.name AS owner_name, m.title AS meeting_title "
        "FROM action_items a "
        "JOIN employees e ON a.owner_id = e.emp_id "
        "LEFT JOIN meetings m ON a.meeting_id = m.meeting_id WHERE 1=1"
    )
    params: List[Any] = []
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    if owner_name:
        sql += " AND e.name LIKE ?"
        params.append(f"%{owner_name}%")
    if overdue_only:
        sql += " AND (a.status = 'overdue' OR (a.status IN ('open','in_progress') AND a.due_date < date('now')))"
    sql += " ORDER BY CASE a.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, a.due_date"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "actions": rows}


def office_list_travel(emp_name: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
    sql = (
        "SELECT t.*, e.name AS emp_name, e.dept FROM travel_requests t "
        "JOIN employees e ON t.emp_id = e.emp_id WHERE 1=1"
    )
    params: List[Any] = []
    if emp_name:
        sql += " AND e.name LIKE ?"
        params.append(f"%{emp_name}%")
    if status:
        sql += " AND t.status = ?"
        params.append(status)
    sql += " ORDER BY t.start_date DESC"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "travels": rows}


def office_get_expense_claim(claim_id: Optional[str] = None, emp_name: Optional[str] = None) -> Dict[str, Any]:
    with _connect() as conn:
        if claim_id:
            cur = conn.execute(
                "SELECT c.*, e.name AS emp_name, e.dept, e.title FROM expense_claims c "
                "JOIN employees e ON c.emp_id = e.emp_id WHERE c.claim_id = ?",
                (claim_id,),
            )
        elif emp_name:
            cur = conn.execute(
                "SELECT c.*, e.name AS emp_name, e.dept, e.title FROM expense_claims c "
                "JOIN employees e ON c.emp_id = e.emp_id WHERE e.name LIKE ?",
                (f"%{emp_name}%",),
            )
        else:
            return {"success": False, "error": "claim_id 或 emp_name 必填"}
        claims = _rows(cur)
        for c in claims:
            c["items"] = _rows(
                conn.execute(
                    "SELECT * FROM expense_items WHERE claim_id = ? ORDER BY item_date",
                    (c["claim_id"],),
                )
            )
            if c.get("travel_id"):
                travels = _rows(
                    conn.execute(
                        "SELECT * FROM travel_requests WHERE travel_id = ?",
                        (c["travel_id"],),
                    )
                )
                c["travel"] = travels[0] if travels else None
    return {"success": True, "count": len(claims), "claims": claims}


def office_list_seal_requests(status: Optional[str] = None, seal_type: Optional[str] = None) -> Dict[str, Any]:
    sql = (
        "SELECT s.*, e.name AS applicant_name, e.dept FROM seal_requests s "
        "JOIN employees e ON s.applicant_id = e.emp_id WHERE 1=1"
    )
    params: List[Any] = []
    if status:
        sql += " AND s.status = ?"
        params.append(status)
    if seal_type:
        sql += " AND s.seal_type LIKE ?"
        params.append(f"%{seal_type}%")
    sql += " ORDER BY s.applied_at DESC"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "seals": rows}


def office_list_supplies(low_stock_only: bool = False) -> Dict[str, Any]:
    sql = "SELECT * FROM supply_items"
    if low_stock_only:
        sql += " WHERE stock_qty < reorder_level"
    sql += " ORDER BY category, sku"
    with _connect() as conn:
        items = _rows(conn.execute(sql))
        reqs = _rows(
            conn.execute(
                "SELECT r.*, e.name AS applicant_name, i.name AS item_name "
                "FROM supply_requests r "
                "JOIN employees e ON r.applicant_id = e.emp_id "
                "JOIN supply_items i ON r.sku = i.sku "
                "ORDER BY r.requested_at DESC"
            )
        )
    return {"success": True, "items": items, "requests": reqs}


def office_submit_minutes_draft(title: str, markdown_body: str) -> Dict[str, Any]:
    """Write meeting minutes draft to outbox (HITL)."""
    _OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:60]
    path = _OUTBOX / f"{ts}_{safe}.md"
    path.write_text(markdown_body, encoding="utf-8")
    return {
        "success": True,
        "message": "纪要草案已写入 outbox，等待人工审批",
        "path": str(path),
        "title": title,
    }


def office_submit_expense_review_note(claim_id: str, conclusion: str, note_markdown: str) -> Dict[str, Any]:
    """Write expense pre-review note to outbox (HITL)."""
    _OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _OUTBOX / f"{ts}_expense_review_{claim_id}.md"
    body = f"# 报销预审意见 `{claim_id}`\n\n**结论**：{conclusion}\n\n{note_markdown}\n"
    path.write_text(body, encoding="utf-8")
    return {
        "success": True,
        "message": "预审意见已写入 outbox，等待人工审批",
        "path": str(path),
        "claim_id": claim_id,
        "conclusion": conclusion,
    }
