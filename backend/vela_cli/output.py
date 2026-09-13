"""CLI output helpers."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

import typer
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

# Shared flag: set by root callback
json_mode: bool = False


def set_json_mode(enabled: bool) -> None:
    global json_mode
    json_mode = enabled


def emit(data: Any, *, columns: Optional[Sequence[str]] = None) -> None:
    if json_mode:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        _print_table(data["items"], columns=columns)
        total = data.get("total")
        if total is not None:
            console.print(f"[dim]total={total} page={data.get('page')} size={data.get('page_size')}[/dim]")
        return
    if isinstance(data, list):
        _print_table(data, columns=columns)
        return
    console.print_json(data=data)


def _print_table(rows: List[Any], columns: Optional[Sequence[str]] = None) -> None:
    if not rows:
        console.print("[dim](empty)[/dim]")
        return
    if not all(isinstance(r, dict) for r in rows):
        console.print_json(data=rows)
        return
    cols = list(columns) if columns else _infer_columns(rows)
    table = Table(show_header=True, header_style="bold")
    for c in cols:
        table.add_column(c)
    for row in rows:
        table.add_row(*[str(row.get(c, "") if row.get(c) is not None else "") for c in cols])
    console.print(table)


def _infer_columns(rows: List[Dict[str, Any]], limit: int = 6) -> List[str]:
    preferred = [
        "agent_id", "tool_id", "skill_pack_id", "kb_id", "approval_id",
        "session_id", "schedule_id", "connector_id", "model_service_id",
        "provider_id", "name", "display_name", "status", "tool_name",
        "category", "created_at",
    ]
    keys = list(rows[0].keys())
    ordered = [k for k in preferred if k in keys]
    for k in keys:
        if k not in ordered:
            ordered.append(k)
        if len(ordered) >= limit:
            break
    return ordered[:limit]


def emit_error(exc: BaseException) -> None:
    from vela_cli.client import VelaApiError

    if isinstance(exc, VelaApiError):
        payload = {"error": True, "status_code": exc.status_code, "body": exc.body}
        if json_mode:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            err_console.print(f"[red]HTTP {exc.status_code}[/red] {exc.body}")
    else:
        if json_mode:
            typer.echo(json.dumps({"error": True, "message": str(exc)}, ensure_ascii=False))
        else:
            err_console.print(f"[red]{exc}[/red]")
