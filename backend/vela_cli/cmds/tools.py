"""Tool management commands."""
from __future__ import annotations

import json
from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Manage tools")


@app.command("list")
def list_tools(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
    keyword: Optional[str] = typer.Option(None, "--keyword", "-k"),
) -> None:
    params = {"page": page, "page_size": page_size}
    if keyword:
        params["keyword"] = keyword
    try:
        with ApiClient() as client:
            data = client.get("/tools", params=params)
        emit(data, columns=["tool_id", "name", "display_name", "tool_type", "status"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_tool(tool_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/tools/{tool_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create")
def create_tool(
    body_json: str = typer.Option(..., "--json-body", help="ToolCreate JSON"),
) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.post("/tools", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("update")
def update_tool(
    tool_id: str = typer.Argument(...),
    body_json: str = typer.Option(..., "--json-body"),
) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.put(f"/tools/{tool_id}", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("delete")
def delete_tool(tool_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.delete(f"/tools/{tool_id}")
        emit(data if data else {"ok": True, "deleted": tool_id})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("test")
def test_tool(
    tool_id: str = typer.Argument(...),
    params_json: str = typer.Option("{}", "--params"),
) -> None:
    try:
        parameters = json.loads(params_json)
        with ApiClient() as client:
            data = client.post(f"/tools/{tool_id}/test", json_body={"parameters": parameters})
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("builtin")
def list_builtin() -> None:
    try:
        with ApiClient() as client:
            data = client.get("/tools/builtin")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
