"""Schedule commands."""
from __future__ import annotations

import json
from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Schedules")


@app.command("list")
def list_schedules(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.get("/schedules", params={"page": page, "page_size": page_size})
        emit(data, columns=["schedule_id", "name", "enabled", "agent_id", "cron"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_schedule(schedule_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/schedules/{schedule_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create")
def create_schedule(body_json: str = typer.Option(..., "--json-body")) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.post("/schedules", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("enable")
def enable_schedule(schedule_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/schedules/{schedule_id}/enable")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("disable")
def disable_schedule(schedule_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/schedules/{schedule_id}/disable")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("trigger")
def trigger_schedule(schedule_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/schedules/{schedule_id}/trigger")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("delete")
def delete_schedule(schedule_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.delete(f"/schedules/{schedule_id}")
        emit(data if data else {"ok": True, "deleted": schedule_id})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
