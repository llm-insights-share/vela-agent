"""Model provider / model-service commands."""
from __future__ import annotations

import json
from typing import Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Providers and model services")


@app.command("providers")
def list_providers(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.get("/providers", params={"page": page, "page_size": page_size})
        emit(data, columns=["provider_id", "display_name", "provider_code", "status"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("list")
def list_services(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.get("/model-services", params={"page": page, "page_size": page_size})
        emit(data, columns=["model_service_id", "display_name", "model_name", "status"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_service(model_service_id: str = typer.Argument(...)) -> None:
    """List endpoint has no single-get; filter list by id."""
    try:
        with ApiClient() as client:
            data = client.get("/model-services", params={"page": 1, "page_size": 200})
        items = data.get("items") or []
        match = next((i for i in items if i.get("model_service_id") == model_service_id), None)
        if not match:
            raise RuntimeError(f"model service not found: {model_service_id}")
        emit(match)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create")
def create_service(body_json: str = typer.Option(..., "--json-body")) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            data = client.post("/model-services", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("test")
def test_service(model_service_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/model-services/{model_service_id}/test")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
