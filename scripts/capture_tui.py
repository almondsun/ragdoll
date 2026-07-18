"""Generate the deterministic README screenshot from the headless Textual driver."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from unittest.mock import patch

from rich.console import ColorSystem

from ragdoll.config import Settings
from ragdoll.providers import FakeProvider
from ragdoll.tui import RagdollApp


def normalized_svg(value: str) -> str:
    """Remove generator whitespace that would fail Git's whitespace check."""
    return "\n".join(line.rstrip() for line in value.splitlines()) + "\n"


async def capture() -> None:
    root = Path(__file__).resolve().parents[1]
    with patch.dict(os.environ, {"FORCE_COLOR": "1"}):
        os.environ.pop("NO_COLOR", None)
        await capture_application(root)


async def capture_application(root: Path) -> None:
    application = RagdollApp(root, Settings(animate=False), FakeProvider([]))
    # Textual disables Rich colors in headless mode; the documentation fixture is intentionally
    # true-color so it matches the real terminal experience regardless of the caller environment.
    application.console._color_system = ColorSystem.TRUECOLOR
    async with application.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        welcome = normalized_svg(application.export_screenshot(title="RAGdoll 2.2.0 welcome"))
        expected_colors = {"#56cfe1", "#9b5de5", "#ff6b6b", "#fff3c4"}
        captured_colors = set(re.findall(r"#[0-9a-f]{6}", welcome.casefold()))
        if not expected_colors <= captured_colors:
            missing = ", ".join(sorted(expected_colors - captured_colors))
            raise RuntimeError(f"TUI welcome capture is missing mascot colors: {missing}")
        (root / "docs" / "assets" / "ragdoll-tui-welcome.svg").write_text(
            welcome,
            encoding="utf-8",
        )
        await pilot.resize_terminal(120, 36)
        await application.add_card(
            "You",
            "I want to understand current video generation models",
            tone="user",
        )
        await application.add_card(
            "What should this investigation optimize for?",
            "Find the current state of the art: compare leading architectures and evidence.",
        )
        await application.add_card(
            "Research plan approved",
            "Video generation model landscape · 6 query families",
            tone="success",
        )
        await application.add_card(
            "Paper collection",
            "24 candidates · 6 staged · Enter to inspect",
        )
        await application.add_card(
            "Research dossier",
            "7 sections · 25 cited claims · Enter to read",
            tone="success",
        )
        await pilot.pause()
        destination = root / "docs" / "assets" / "ragdoll-tui.svg"
        destination.write_text(
            normalized_svg(application.export_screenshot(title="RAGdoll 2.2.0 terminal workspace")),
            encoding="utf-8",
        )


if __name__ == "__main__":
    asyncio.run(capture())
