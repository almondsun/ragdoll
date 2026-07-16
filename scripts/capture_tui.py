"""Generate the deterministic README screenshot from the headless Textual driver."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ragdoll.config import Settings
from ragdoll.providers import FakeProvider
from ragdoll.tui import RagdollApp


async def capture() -> None:
    root = Path(__file__).resolve().parents[1]
    application = RagdollApp(root, Settings(animate=False), FakeProvider([]))
    async with application.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        (root / "docs" / "assets" / "ragdoll-tui-welcome.svg").write_text(
            application.export_screenshot(title="RAGdoll 2.0 welcome"),
            encoding="utf-8",
        )
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
            application.export_screenshot(title="RAGdoll 2.0 terminal workspace"),
            encoding="utf-8",
        )


if __name__ == "__main__":
    asyncio.run(capture())
