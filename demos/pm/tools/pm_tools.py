"""PM demo local_python tools — product analytics / backlog mock SQLite."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DATA_DIR / "demo_pm.db"
_OUTBOX = Path(__file__).resolve().parent.parent / "outbox"


def _connect() -> sqlite3.Connection:
    if not _DB_PATH.exists():
        raise FileNotFoundError(
            f"PM demo DB not found: {_DB_PATH}. Run seed_demo.py first."
        )
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def pm_list_products() -> Dict[str, Any]:
    with _connect() as conn:
        rows = _rows(conn.execute("SELECT * FROM products ORDER BY product_id"))
    return {"success": True, "count": len(rows), "products": rows}


def pm_list_roadmap(product_code: Optional[str] = None, quarter: Optional[str] = None) -> Dict[str, Any]:
    sql = (
        "SELECT r.*, p.name AS product_name, p.code AS product_code FROM roadmap_items r "
        "JOIN products p ON r.product_id = p.product_id WHERE 1=1"
    )
    params: List[Any] = []
    if product_code:
        sql += " AND (p.code = ? OR p.name LIKE ?)"
        params.extend([product_code, f"%{product_code}%"])
    if quarter:
        sql += " AND r.quarter = ?"
        params.append(quarter)
    sql += " ORDER BY r.quarter, CASE r.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "roadmap": rows}


def pm_list_backlog(
    product_code: Optional[str] = None,
    status: Optional[str] = None,
    top_n: int = 10,
) -> Dict[str, Any]:
    top_n = max(1, min(int(top_n), 50))
    sql = (
        "SELECT b.*, p.name AS product_name, p.code AS product_code FROM backlog_items b "
        "JOIN products p ON b.product_id = p.product_id WHERE 1=1"
    )
    params: List[Any] = []
    if product_code:
        sql += " AND (p.code = ? OR p.name LIKE ?)"
        params.extend([product_code, f"%{product_code}%"])
    if status:
        sql += " AND b.status = ?"
        params.append(status)
    sql += " ORDER BY b.priority_score DESC LIMIT ?"
    params.append(top_n)
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "backlog": rows}


def pm_list_competitors(category: Optional[str] = None) -> Dict[str, Any]:
    sql = "SELECT * FROM competitors WHERE 1=1"
    params: List[Any] = []
    if category:
        sql += " AND category LIKE ?"
        params.append(f"%{category}%")
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "competitors": rows}


def pm_get_competitor_matrix(competitor_name: Optional[str] = None) -> Dict[str, Any]:
    with _connect() as conn:
        if competitor_name:
            comps = _rows(
                conn.execute(
                    "SELECT * FROM competitors WHERE name LIKE ?",
                    (f"%{competitor_name}%",),
                )
            )
        else:
            comps = _rows(conn.execute("SELECT * FROM competitors ORDER BY name"))
        for c in comps:
            c["features"] = _rows(
                conn.execute(
                    "SELECT feature_name, support_level, notes FROM competitor_features "
                    "WHERE competitor_id = ? ORDER BY feature_name",
                    (c["competitor_id"],),
                )
            )
    return {"success": True, "count": len(comps), "competitors": comps}


def pm_list_feedback(
    product_code: Optional[str] = None,
    theme: Optional[str] = None,
    sentiment: Optional[str] = None,
) -> Dict[str, Any]:
    sql = (
        "SELECT f.*, p.code AS product_code FROM user_feedback f "
        "JOIN products p ON f.product_id = p.product_id WHERE 1=1"
    )
    params: List[Any] = []
    if product_code:
        sql += " AND (p.code = ? OR p.name LIKE ?)"
        params.extend([product_code, f"%{product_code}%"])
    if theme:
        sql += " AND f.theme LIKE ?"
        params.append(f"%{theme}%")
    if sentiment:
        sql += " AND f.sentiment = ?"
        params.append(sentiment)
    sql += " ORDER BY f.created_at DESC"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "feedback": rows}


def pm_list_interviews(product_code: Optional[str] = None) -> Dict[str, Any]:
    sql = (
        "SELECT i.*, p.code AS product_code FROM research_interviews i "
        "JOIN products p ON i.product_id = p.product_id WHERE 1=1"
    )
    params: List[Any] = []
    if product_code:
        sql += " AND (p.code = ? OR p.name LIKE ?)"
        params.extend([product_code, f"%{product_code}%"])
    sql += " ORDER BY i.interviewed_at DESC"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "interviews": rows}


def pm_query_metrics(
    product_code: str = "approval-hub",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    sql = (
        "SELECT m.* FROM metrics_daily m "
        "JOIN products p ON m.product_id = p.product_id "
        "WHERE (p.code = ? OR p.name LIKE ?)"
    )
    params: List[Any] = [product_code, f"%{product_code}%"]
    if date_from:
        sql += " AND m.metric_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND m.metric_date <= ?"
        params.append(date_to)
    sql += " ORDER BY m.metric_date"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    summary = {}
    if rows:
        summary = {
            "days": len(rows),
            "dau_first": rows[0]["dau"],
            "dau_last": rows[-1]["dau"],
            "dau_delta": (rows[-1]["dau"] or 0) - (rows[0]["dau"] or 0),
            "activation_last": rows[-1]["activation_rate"],
            "retention_d7_last": rows[-1]["retention_d7"],
            "nps_last": rows[-1]["nps"],
        }
    return {"success": True, "product_code": product_code, "summary": summary, "series": rows}


def pm_query_funnel(product_code: str = "approval-hub") -> Dict[str, Any]:
    sql = (
        "SELECT f.* FROM funnel_weekly f "
        "JOIN products p ON f.product_id = p.product_id "
        "WHERE (p.code = ? OR p.name LIKE ?) ORDER BY f.week_start"
    )
    with _connect() as conn:
        rows = _rows(conn.execute(sql, [product_code, f"%{product_code}%"]))
    return {"success": True, "product_code": product_code, "weeks": rows}


def pm_list_events(product_code: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
    sql = (
        "SELECT e.*, p.code AS product_code FROM event_definitions e "
        "JOIN products p ON e.product_id = p.product_id WHERE 1=1"
    )
    params: List[Any] = []
    if product_code:
        sql += " AND (p.code = ? OR p.name LIKE ?)"
        params.extend([product_code, f"%{product_code}%"])
    if status:
        sql += " AND e.status = ?"
        params.append(status)
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "events": rows}


def pm_list_experiments(product_code: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
    sql = (
        "SELECT x.*, p.code AS product_code FROM experiments x "
        "JOIN products p ON x.product_id = p.product_id WHERE 1=1"
    )
    params: List[Any] = []
    if product_code:
        sql += " AND (p.code = ? OR p.name LIKE ?)"
        params.extend([product_code, f"%{product_code}%"])
    if status:
        sql += " AND x.status = ?"
        params.append(status)
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "experiments": rows}


def pm_list_prds(product_code: Optional[str] = None) -> Dict[str, Any]:
    sql = (
        "SELECT d.*, p.code AS product_code FROM prd_docs d "
        "JOIN products p ON d.product_id = p.product_id WHERE 1=1"
    )
    params: List[Any] = []
    if product_code:
        sql += " AND (p.code = ? OR p.name LIKE ?)"
        params.extend([product_code, f"%{product_code}%"])
    sql += " ORDER BY d.updated_at DESC"
    with _connect() as conn:
        rows = _rows(conn.execute(sql, params))
    return {"success": True, "count": len(rows), "prds": rows}


def pm_submit_prd_draft(title: str, markdown_body: str) -> Dict[str, Any]:
    _OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:60]
    path = _OUTBOX / f"{ts}_{safe}.md"
    path.write_text(markdown_body, encoding="utf-8")
    return {
        "success": True,
        "message": "PRD 草案已写入 outbox，等待人工审批",
        "path": str(path),
        "title": title,
    }
