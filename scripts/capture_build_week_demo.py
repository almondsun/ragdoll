"""Capture truthful Build Week demo frames from the saved acceptance investigation."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from rich.console import ColorSystem
from textual.pilot import Pilot
from textual.widgets import TextArea

from ragdoll.config import Settings
from ragdoll.providers import FakeProvider
from ragdoll.storage import Workspace
from ragdoll.tui import DetailScreen, PapersScreen, RagdollApp, TimelineCard

INVESTIGATION_ID = "d47140cc0bd5"
PREFERRED_CITATION = "chunk-b97b8d69e3f5e5826ef41fa8"
TERMINAL_SIZE = (120, 32)


def normalized_svg(value: str) -> str:
    """Remove generator whitespace that would fail Git's whitespace check."""
    return "\n".join(line.rstrip() for line in value.splitlines()) + "\n"


async def wait_for(
    pilot: Pilot[object], predicate: Callable[[], bool], attempts: int = 100
) -> None:
    """Wait for a deterministic Textual state without adding production dependencies."""
    for _ in range(attempts):
        await pilot.pause(0.02)
        if predicate():
            return
    raise RuntimeError("demo capture did not reach the expected Textual state")


def write_frame(application: RagdollApp, output: Path, name: str) -> None:
    svg = normalized_svg(application.export_screenshot(title=f"RAGdoll demo · {name}"))
    colors = set(re.findall(r"#[0-9a-fA-F]{6}", svg))
    chromatic = {
        color
        for color in colors
        if max(bytes.fromhex(color[1:])) - min(bytes.fromhex(color[1:])) >= 24
    }
    if len(chromatic) < 6:
        raise RuntimeError(f"demo capture lost its color palette: {sorted(chromatic)}")
    svg_path = output / f"{name}.svg"
    png_path = output / f"{name}.png"
    svg_path.write_text(svg, encoding="utf-8")
    converter = shutil.which("rsvg-convert")
    if converter is None:
        raise RuntimeError("rsvg-convert is required to create demo PNG frames")
    subprocess.run(
        [converter, "--width", "1920", "--height", "1080", str(svg_path), "-o", str(png_path)],
        check=True,
    )


async def capture(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    workspace = Workspace(root)
    investigation = workspace.load(INVESTIGATION_ID)
    dossier = workspace.load_dossier(INVESTIGATION_ID)
    if dossier is None or len(dossier.sections) != 7:
        raise RuntimeError("the documented seven-section acceptance dossier is unavailable")
    cited_ids = {
        chunk_id
        for section in dossier.sections
        for claim in section.claims
        for chunk_id in claim.chunk_ids
    }
    if PREFERRED_CITATION not in cited_ids:
        raise RuntimeError("the selected demo citation is unavailable in the acceptance dossier")

    with patch.dict(os.environ, {"FORCE_COLOR": "1"}):
        os.environ.pop("NO_COLOR", None)
        settings = Settings(provider="ollama", ollama_model="qwen3:4b", animate=False)
        application = RagdollApp(root, settings, FakeProvider([]), investigation=investigation)
        application.console._color_system = ColorSystem.TRUECOLOR
        async with application.run_test(size=TERMINAL_SIZE) as pilot:
            await wait_for(
                pilot,
                lambda: (
                    not application._workflow_pending
                    and application.query_one("#composer", TextArea).has_focus
                ),
            )
            write_frame(application, output, "01-resumed-investigation")

            await application._show_plan()
            await wait_for(pilot, lambda: isinstance(application.screen, DetailScreen))
            write_frame(application, output, "02-approved-plan")
            await pilot.press("escape")

            papers_worker = application.run_worker(application._show_papers())
            await wait_for(pilot, lambda: isinstance(application.screen, PapersScreen))
            await pilot.press("f")
            write_frame(application, output, "03-curated-papers")
            await pilot.press("escape")
            await papers_worker.wait()

            await application._show_sources()
            sources = [
                card
                for card in application.query(TimelineCard)
                if card.card_title == "Evidence sources"
            ]
            sources[-1].focus()
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(application.screen, DetailScreen))
            write_frame(application, output, "04-evidence-sources")
            await pilot.press("escape")

            await application._show_dossier(dossier)
            dossier_cards = [
                card
                for card in application.query(TimelineCard)
                if card.card_title == "Research dossier"
            ]
            dossier_cards[-1].focus()
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(application.screen, DetailScreen))
            write_frame(application, output, "05-cited-dossier")
            await pilot.press("escape")

            await application._show_evidence(PREFERRED_CITATION)
            evidence = [
                card
                for card in application.query(TimelineCard)
                if card.card_title == "Evidence passage"
            ]
            evidence[-1].focus()
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(application.screen, DetailScreen))
            write_frame(application, output, "06-exact-passage")

    expected = {
        f"{index:02d}-{name}.png"
        for index, name in enumerate(
            (
                "resumed-investigation",
                "approved-plan",
                "curated-papers",
                "evidence-sources",
                "cited-dossier",
                "exact-passage",
            ),
            1,
        )
    }
    actual = {path.name for path in output.glob("*.png")}
    if actual != expected:
        raise RuntimeError(f"unexpected demo frame set: {sorted(actual)}")
    if any(not re.fullmatch(r"[0-9]{2}-[a-z-]+\.png", name) for name in actual):
        raise RuntimeError("demo frame names are not deterministic")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "docs" / "assets" / "OpenAI Build Week" / "production" / "frames"
    asyncio.run(capture(root, output))


if __name__ == "__main__":
    main()
