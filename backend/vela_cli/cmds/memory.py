"""Memory management commands (Letta passages / scopes)."""
from __future__ import annotations

from typing import List, Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Manage platform memory (Letta passages/scopes)")


@app.command("scopes")
def list_scopes() -> None:
    try:
        with ApiClient() as client:
            data = client.get("/memory/scopes")
        emit(data, columns=["mapping_id", "agent_id", "user_id", "username", "letta_agent_id"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("passages")
def list_passages(
    agent_id: str = typer.Option(..., "--agent-id", help="Target agent id (memory scope)"),
    user_id: str = typer.Option("", "--user-id", help="Optional user scope"),
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
    query: Optional[str] = typer.Option(None, "--query", "-q"),
) -> None:
    params = {
        "agent_id": agent_id,
        "user_id": user_id or "",
        "page": page,
        "page_size": page_size,
    }
    if query:
        params["query"] = query
    try:
        with ApiClient() as client:
            data = client.get("/memory/passages", params=params)
        emit(data, columns=["passage_id", "content", "tags", "created_at"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create-passage")
def create_passage(
    agent_id: str = typer.Option(..., "--agent-id"),
    text: str = typer.Option(..., "--text", help="Memory text content"),
    user_id: str = typer.Option("", "--user-id"),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Repeatable tag"),
) -> None:
    payload = {
        "agent_id": agent_id,
        "user_id": user_id or "",
        "text": text,
        "tags": list(tag or []),
    }
    try:
        with ApiClient() as client:
            data = client.post("/memory/passages", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("delete-passage")
def delete_passage(
    passage_id: str = typer.Argument(...),
    agent_id: str = typer.Option(..., "--agent-id"),
    user_id: str = typer.Option("", "--user-id"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.delete(
                f"/memory/passages/{passage_id}",
                params={"agent_id": agent_id, "user_id": user_id or ""},
            )
        emit(data if data else {"ok": True, "deleted": passage_id})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
