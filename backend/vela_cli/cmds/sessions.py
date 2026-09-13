"""Session read commands."""
from __future__ import annotations

from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Sessions (read-only)")


@app.command("list")
def list_sessions(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
    agent_id: Optional[str] = typer.Option(None, "--agent-id"),
    status: Optional[str] = typer.Option(None, "--status"),
) -> None:
    params = {"page": page, "page_size": page_size}
    if agent_id:
        params["agent_id"] = agent_id
    if status:
        params["status"] = status
    try:
        with ApiClient() as client:
            data = client.get("/sessions", params=params)
        emit(data, columns=["session_id", "agent_id", "status", "caller_id", "updated_at"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_session(session_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/sessions/{session_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
