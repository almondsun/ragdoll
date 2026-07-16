"""Single source of truth for RAGdoll's interactive command vocabulary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    usage: str
    description: str


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("plan", "/plan", "Inspect the approved research plan."),
    CommandSpec("papers", "/papers", "Browse, inspect, stage, and unstage papers."),
    CommandSpec(
        "dossier",
        "/dossier [refresh SECTION]",
        "Build, inspect, or refresh the evidence dossier.",
    ),
    CommandSpec("ask", "/ask QUESTION", "Ask a question grounded in indexed evidence."),
    CommandSpec("evidence", "/evidence CITATION", "Inspect one cited evidence passage."),
    CommandSpec("sources", "/sources", "Inspect acquired evidence and provenance."),
    CommandSpec("export", "/export", "Export the reading list and dossier."),
    CommandSpec("purge", "/purge", "Delete cached evidence and the dossier."),
    CommandSpec("help", "/help", "Open commands and keyboard help."),
    CommandSpec("quit", "/quit", "Save and exit RAGdoll."),
)

COMMAND_NAMES = frozenset(command.name for command in COMMANDS)

V1_MIGRATIONS: dict[str, str] = {
    "brief": "/plan",
    "candidates": "/papers",
    "inspect": "/papers",
    "stage": "/papers",
    "staged": "/papers",
    "unstage": "/papers",
    "purge-evidence": "/purge",
}


def parse_command(text: str) -> tuple[str, str]:
    """Split a leading-slash command into normalized name and argument text."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", stripped
    parts = stripped[1:].split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0].casefold(), parts[1].strip() if len(parts) == 2 else ""


def migration_hint(name: str) -> str | None:
    replacement = V1_MIGRATIONS.get(name.casefold())
    if replacement is None:
        return None
    return f"/{name} was replaced in RAGdoll 2.0. Use {replacement}."


def command_help() -> str:
    rows = "\n".join(f"- `{item.usage}` — {item.description}" for item in COMMANDS)
    return f"# RAGdoll commands\n\n{rows}"
