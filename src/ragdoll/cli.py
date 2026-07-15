"""RAGdoll command-line entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import load_settings
from .export import export_investigation
from .interactive import InteractiveResearch
from .providers import ProviderError, make_provider
from .storage import Workspace

app = typer.Typer(no_args_is_help=False, help="Explainable scholarly research from your terminal.")
console = Console()


def _root() -> Path:
    return Path.cwd()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    topic: Annotated[
        str | None, typer.Option("--topic", "-t", help="Optional initial research topic")
    ] = None,
    provider: Annotated[str | None, typer.Option(help="openai or ollama")] = None,
    no_animation: Annotated[bool, typer.Option("--no-animation")] = False,
    version: Annotated[bool, typer.Option("--version", is_eager=True)] = False,
) -> None:
    if version:
        console.print(f"ragdoll {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    settings = load_settings(_root(), provider=provider, animate=not no_animation)
    try:
        InteractiveResearch(_root(), settings, make_provider(settings), console).start(topic)
    except (ProviderError, ValueError) as error:
        console.print(f"[red]RAGdoll could not start:[/red] {error}")
        raise typer.Exit(2) from error
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Investigation saved. Resume with `ragdoll resume`.[/dim]")


@app.command()
def init() -> None:
    """Initialize a RAGdoll workspace in the current directory."""
    workspace = Workspace(_root())
    workspace.initialize()
    console.print(f"Initialized {workspace.directory}")


@app.command("resume")
def resume_command(
    investigation_id: Annotated[str | None, typer.Argument()] = None,
    provider: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Resume the latest or selected investigation."""
    workspace = Workspace(_root())
    try:
        investigation = workspace.load(investigation_id) if investigation_id else workspace.latest()
        settings = load_settings(_root(), provider=provider)
        InteractiveResearch(_root(), settings, make_provider(settings), console).resume(
            investigation
        )
    except (KeyError, ProviderError) as error:
        console.print(f"[red]Cannot resume:[/red] {error}")
        raise typer.Exit(2) from error


@app.command("investigations")
def investigations_command() -> None:
    """List saved investigations."""
    table = Table("ID", "Status", "Updated", "Topic")
    for investigation in Workspace(_root()).list():
        table.add_row(
            investigation.id,
            investigation.status,
            investigation.updated_at.isoformat(timespec="seconds"),
            investigation.original_prompt,
        )
    console.print(table)


@app.command()
def show(investigation_id: str) -> None:
    """Show a saved investigation as JSON."""
    try:
        console.print_json(Workspace(_root()).load(investigation_id).model_dump_json())
    except KeyError as error:
        console.print(f"[red]Unknown investigation:[/red] {investigation_id}")
        raise typer.Exit(2) from error


@app.command("export")
def export_command(
    investigation_id: str,
    format: Annotated[str, typer.Option()] = "markdown",
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Export a saved investigation."""
    suffix = {"markdown": "md", "bibtex": "bib", "json": "json"}.get(format)
    if suffix is None:
        raise typer.BadParameter("format must be markdown, bibtex, or json")
    investigation = Workspace(_root()).load(investigation_id)
    destination = output or (_root() / ".ragdoll" / "exports" / f"{investigation_id}.{suffix}")
    export_investigation(investigation, destination, format)
    console.print(destination)


@app.command()
def doctor() -> None:
    """Check configuration and optional provider availability."""
    settings = load_settings(_root())
    console.print(f"Python: {sys.version.split()[0]}")
    console.print(f"Provider: {settings.provider}")
    if settings.provider == "openai":
        console.print(
            "OPENAI_API_KEY: set" if os.getenv("OPENAI_API_KEY") else "OPENAI_API_KEY: missing"
        )
    else:
        console.print(f"Ollama: {settings.ollama_url} ({settings.ollama_model})")


if __name__ == "__main__":
    app()
