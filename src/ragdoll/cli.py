"""RAGdoll command-line entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import load_settings
from .export import export_dossier, export_investigation
from .interactive import InteractiveResearch
from .providers import ProviderError, make_provider
from .storage import Workspace

app = typer.Typer(no_args_is_help=False, help="Explainable scholarly research from your terminal.")
console = Console()


def _root() -> Path:
    return Path.cwd()


def _require_interactive_tty() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty() or os.getenv("TERM") == "dumb":
        console.print(
            "[red]RAGdoll could not start:[/red] interactive mode requires a TTY; "
            "use `ragdoll investigations`, `show`, or `export` for non-interactive workflows"
        )
        raise typer.Exit(2)


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
    _require_interactive_tty()
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
    _require_interactive_tty()
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
    for investigation in Workspace(_root()).list_investigations():
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
    suffix = {
        "markdown": "md",
        "bibtex": "bib",
        "json": "json",
        "dossier": "dossier.md",
        "dossier-json": "dossier.json",
    }.get(format)
    if suffix is None:
        raise typer.BadParameter("format must be markdown, bibtex, json, dossier, or dossier-json")
    workspace = Workspace(_root())
    investigation = workspace.load(investigation_id)
    destination = output or (_root() / ".ragdoll" / "exports" / f"{investigation_id}.{suffix}")
    if format.startswith("dossier"):
        dossier = workspace.load_dossier(investigation_id)
        if dossier is None:
            raise typer.BadParameter("this investigation has no dossier")
        chunk_ids = [
            item
            for section in dossier.sections
            for claim in section.claims
            for item in claim.chunk_ids
        ]
        export_dossier(
            dossier,
            investigation,
            workspace.chunks(chunk_ids),
            destination,
            "json" if format == "dossier-json" else "markdown",
        )
    else:
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
        try:
            response = httpx.get(f"{settings.ollama_url}/api/tags", timeout=3)
            response.raise_for_status()
            models = {
                model.get("name", "").removesuffix(":latest")
                for model in response.json().get("models", [])
            }
            expected = settings.ollama_model.removesuffix(":latest")
            state = "available" if expected in models else "not pulled"
            console.print(f"Ollama server: reachable; model: {state}")
        except (httpx.HTTPError, ValueError):
            console.print("Ollama server: unreachable")


if __name__ == "__main__":
    app()
