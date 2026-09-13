"""Connector commands."""
from __future__ import annotations

import json
from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Connectors / MCP")


@app.command("list")
def list_connectors() -> None:
    try:
        with ApiClient() as client:
            data = client.get("/connectors")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("catalog")
def catalog() -> None:
    try:
        with ApiClient() as client:
            data = client.get("/connectors/catalog")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_connector(connector_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/connectors/{connector_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create")
def create_connector(body_json: str = typer.Option(..., "--json-body")) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.post("/connectors", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("sync")
def sync_connector(connector_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/connectors/{connector_id}/sync")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("delete")
def delete_connector(connector_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.delete(f"/connectors/{connector_id}")
        emit(data if data else {"ok": True, "deleted": connector_id})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
