"""Persist code execution records to database."""

from typing import Any, Dict, Optional

from models import CodeExecution, gen_uuid


def persist_execution(
    db,
    *,
    session_id: str,
    agent_id: str,
    result: Dict[str, Any],
) -> Optional[str]:
    if not result.get("code"):
        return None

    status = "SUCCESS" if result.get("success") else "ERROR"
    if result.get("timed_out") or "超时" in str(result.get("error", "")):
        status = "TIMEOUT"

    row = CodeExecution(
        execution_id=gen_uuid(),
        session_id=session_id,
        agent_id=agent_id or "",
        language=result.get("language", "python"),
        code=result.get("code", ""),
        stdout=(result.get("stdout") or "")[:10000],
        stderr=(result.get("stderr") or "")[:5000],
        exit_code=int(result.get("exit_code") or 0),
        duration_ms=int(result.get("duration_ms") or 0),
        artifacts=result.get("artifacts") or [],
        status=status,
        error_message=(result.get("error") or "")[:5000],
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        return None
    return row.execution_id
