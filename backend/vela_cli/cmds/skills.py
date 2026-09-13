"""Skill pack commands."""
from __future__ import annotations

import json
from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Manage skill packs")


@app.command("list")
def list_skills(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
    keyword: Optional[str] = typer.Option(None, "--keyword", "-k"),
) -> None:
    params = {"page": page, "page_size": page_size}
    if keyword:
        params["keyword"] = keyword
    try:
        with ApiClient() as client:
            data = client.get("/skills", params=params)
        emit(data, columns=["skill_pack_id", "name", "version", "status"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_skill(skill_pack_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/skills/{skill_pack_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create")
def create_skill(body_json: str = typer.Option(..., "--json-body")) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.post("/skills", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("update")
def update_skill(
    skill_pack_id: str = typer.Argument(...),
    body_json: str = typer.Option(..., "--json-body"),
) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.put(f"/skills/{skill_pack_id}", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("publish")
def publish_skill(skill_pack_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/skills/{skill_pack_id}/publish")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("unpublish")
def unpublish_skill(skill_pack_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/skills/{skill_pack_id}/unpublish")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("delete")
def delete_skill(skill_pack_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.delete(f"/skills/{skill_pack_id}")
        emit(data if data else {"ok": True, "deleted": skill_pack_id})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
