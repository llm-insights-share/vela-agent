"""Knowledge base commands."""
from __future__ import annotations

import json
from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Manage knowledge bases")


@app.command("list")
def list_kb(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
    keyword: Optional[str] = typer.Option(None, "--keyword", "-k"),
) -> None:
    params = {"page": page, "page_size": page_size}
    if keyword:
        params["keyword"] = keyword
    try:
        with ApiClient() as client:
            data = client.get("/knowledge-bases", params=params)
        emit(data, columns=["kb_id", "name", "status", "scope"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_kb(kb_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/knowledge-bases/{kb_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create")
def create_kb(body_json: str = typer.Option(..., "--json-body")) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.post("/knowledge-bases", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("update")
def update_kb(
    kb_id: str = typer.Argument(...),
    body_json: str = typer.Option(..., "--json-body"),
) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.put(f"/knowledge-bases/{kb_id}", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("delete")
def delete_kb(kb_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.delete(f"/knowledge-bases/{kb_id}")
        emit(data if data else {"ok": True, "deleted": kb_id})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("search")
def search_kb(
    kb_id: str = typer.Argument(...),
    query: str = typer.Option(..., "--query", "-q"),
    top_k: int = typer.Option(5, "--top-k"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.post(
                f"/knowledge-bases/{kb_id}/search",
                json_body={"query": query, "top_k": top_k},
            )
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
