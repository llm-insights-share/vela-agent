"""Approval center commands."""
from __future__ import annotations

from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Approvals / HITL")


@app.command("list")
def list_approvals(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
    status: Optional[str] = typer.Option("PENDING", "--status"),
    category: Optional[str] = typer.Option(None, "--category"),
) -> None:
    params = {"page": page, "page_size": page_size}
    if status:
        params["status"] = status
    if category:
        params["category"] = category
    try:
        with ApiClient() as client:
            data = client.get("/approvals", params=params)
        emit(
            data,
            columns=["approval_id", "session_id", "tool_name", "category", "status", "created_at"],
        )
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_approval(approval_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/approvals/{approval_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("approve")
def approve(
    session_id: str = typer.Option(..., "--session-id"),
    approval_id: str = typer.Argument(...),
    reviewer: str = typer.Option("vela-cli", "--reviewer"),
    comment: str = typer.Option("", "--comment"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.post(
                f"/sessions/{session_id}/approvals/{approval_id}/approve",
                json_body={"approved": True, "reviewer": reviewer, "comment": comment},
            )
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("reject")
def reject(
    session_id: str = typer.Option(..., "--session-id"),
    approval_id: str = typer.Argument(...),
    reviewer: str = typer.Option("vela-cli", "--reviewer"),
    comment: str = typer.Option("", "--comment"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.post(
                f"/sessions/{session_id}/approvals/{approval_id}/reject",
                json_body={"approved": False, "reviewer": reviewer, "comment": comment},
            )
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
