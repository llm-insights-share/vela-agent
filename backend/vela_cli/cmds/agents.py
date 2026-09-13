"""Agent management commands."""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from vela_cli.client import ApiClient
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Manage agents")

from services.platform_agents import OPS_AGENT_NAME, is_protected_agent_name


def _guard_ops_self(agent_id_or_name: str, action: str) -> None:
    """Block destructive ops on the built-in ops assistant when identified by name."""
    if is_protected_agent_name(agent_id_or_name) and action in ("delete", "deprecate"):
        raise RuntimeError(f"Refusing to {action} built-in agent {OPS_AGENT_NAME}")


@app.command("list")
def list_agents(
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(50, "--page-size"),
    status: Optional[str] = typer.Option(None, "--status"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Filter by name substring"),
) -> None:
    params = {"page": page, "page_size": page_size}
    if status:
        params["status"] = status
    if name:
        params["name"] = name
    try:
        with ApiClient() as client:
            data = client.get("/agents", params=params)
        emit(data, columns=["agent_id", "name", "status", "agent_type", "updated_at"])
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("get")
def get_agent(agent_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.get(f"/agents/{agent_id}")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("create")
def create_agent(
    name: str = typer.Option(..., "--name"),
    model_service_id: str = typer.Option(..., "--model-service-id"),
    description: str = typer.Option("", "--description"),
    system_prompt: str = typer.Option("", "--system-prompt"),
    agent_type: str = typer.Option("SINGLE", "--agent-type"),
    body_json: Optional[str] = typer.Option(None, "--json-body", help="Full AgentCreate JSON (overrides flags)"),
) -> None:
    try:
        if body_json:
            payload = json.loads(body_json)
        else:
            payload = {
                "name": name,
                "model_service_id": model_service_id,
                "description": description,
                "system_prompt": system_prompt,
                "agent_type": agent_type,
            }
        with ApiClient() as client:
            data = client.post("/agents", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("update")
def update_agent(
    agent_id: str = typer.Argument(...),
    body_json: str = typer.Option(..., "--json-body"),
) -> None:
    try:
        payload = json.loads(body_json)
        with ApiClient() as client:
            # Guard: look up name
            existing = client.get(f"/agents/{agent_id}")
            if existing.get("name") == OPS_AGENT_NAME and payload.get("name") and payload["name"] != OPS_AGENT_NAME:
                raise RuntimeError(f"Refusing to rename built-in agent {OPS_AGENT_NAME}")
            data = client.put(f"/agents/{agent_id}", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("delete")
def delete_agent(agent_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            existing = client.get(f"/agents/{agent_id}")
            _guard_ops_self(existing.get("name") or "", "delete")
            data = client.delete(f"/agents/{agent_id}")
        emit(data if data else {"ok": True, "deleted": agent_id})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("publish")
def publish_agent(
    agent_id: str = typer.Argument(...),
    change_summary: str = typer.Option("", "--change-summary"),
) -> None:
    try:
        with ApiClient() as client:
            data = client.post(
                f"/agents/{agent_id}/publish",
                json_body={"change_summary": change_summary},
            )
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("deprecate")
def deprecate_agent(agent_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            existing = client.get(f"/agents/{agent_id}")
            _guard_ops_self(existing.get("name") or "", "deprecate")
            data = client.post(f"/agents/{agent_id}/deprecate")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("republish")
def republish_agent(agent_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/agents/{agent_id}/republish")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("bind-tools")
def bind_tools(
    agent_id: str = typer.Argument(...),
    tool_ids: Optional[List[str]] = typer.Option(None, "--tool-id"),
    body_json: Optional[str] = typer.Option(None, "--json-body", help='e.g. [{"tool_id":"...","require_approval":true}]'),
) -> None:
    try:
        if body_json:
            payload = json.loads(body_json)
        else:
            payload = list(tool_ids or [])
        with ApiClient() as client:
            data = client.put(f"/agents/{agent_id}/tools", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("bind-skills")
def bind_skills(
    agent_id: str = typer.Argument(...),
    skill_ids: Optional[List[str]] = typer.Option(None, "--skill-id"),
    body_json: Optional[str] = typer.Option(None, "--json-body"),
) -> None:
    try:
        payload = json.loads(body_json) if body_json else list(skill_ids or [])
        with ApiClient() as client:
            data = client.put(f"/agents/{agent_id}/skills", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("bind-kb")
def bind_kb(
    agent_id: str = typer.Argument(...),
    kb_ids: Optional[List[str]] = typer.Option(None, "--kb-id"),
    body_json: Optional[str] = typer.Option(None, "--json-body"),
) -> None:
    try:
        payload = json.loads(body_json) if body_json else list(kb_ids or [])
        with ApiClient() as client:
            data = client.put(f"/agents/{agent_id}/knowledge-bases", json_body=payload)
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("validate")
def validate_agent(agent_id: str = typer.Argument(...)) -> None:
    try:
        with ApiClient() as client:
            data = client.post(f"/agents/{agent_id}/validate")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
