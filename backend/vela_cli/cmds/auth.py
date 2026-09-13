"""Auth commands."""
from __future__ import annotations

import typer

from vela_cli.client import ApiClient, get_api_base, save_credentials, clear_credentials
from vela_cli.output import emit, emit_error

app = typer.Typer(help="Authentication")


@app.command("login")
def login(
    username: str = typer.Option(..., "--username", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
) -> None:
    """Login and save token to ~/.vela/credentials.json."""
    try:
        with ApiClient(token="") as client:
            body = {"username": username, "password": password}
            data = client.post(
                "/auth/login",
                auth=False,
                data=body,
                content_type="application/x-www-form-urlencoded",
            )
        token = data.get("access_token") or ""
        if not token:
            raise RuntimeError(f"login response missing access_token: {data}")
        save_credentials(token, get_api_base())
        emit({"ok": True, "api_base": get_api_base(), "token_saved": True})
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc


@app.command("logout")
def logout() -> None:
    clear_credentials()
    emit({"ok": True, "logged_out": True})


@app.command("whoami")
def whoami() -> None:
    try:
        with ApiClient() as client:
            data = client.get("/auth/me")
        emit(data)
    except Exception as exc:
        emit_error(exc)
        raise typer.Exit(1) from exc
