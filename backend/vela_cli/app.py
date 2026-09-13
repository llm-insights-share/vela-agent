"""Typer application entry."""
from __future__ import annotations

import typer

from vela_cli import __version__
from vela_cli.cmds import agents, approvals, auth, connectors, kb, memory, models, schedules, sessions, skills, tools
from vela_cli.output import set_json_mode

app = typer.Typer(
    name="vela",
    help="Vela platform management CLI (calls /api/v1 REST APIs).",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON (recommended for agents).",
    ),
) -> None:
    set_json_mode(json_output)


@app.command("version")
def version() -> None:
    typer.echo(__version__)


app.add_typer(auth.app, name="auth")
app.add_typer(agents.app, name="agents")
app.add_typer(tools.app, name="tools")
app.add_typer(skills.app, name="skills")
app.add_typer(kb.app, name="kb")
app.add_typer(approvals.app, name="approvals")
app.add_typer(sessions.app, name="sessions")
app.add_typer(models.app, name="models")
app.add_typer(schedules.app, name="schedules")
app.add_typer(connectors.app, name="connectors")
app.add_typer(memory.app, name="memory")


def run() -> None:
    app()
