"""Public adapter for launching the fullscreen RAGdoll terminal application."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from .config import Settings
from .domain import Investigation
from .providers import ModelProvider
from .tui import RagdollApp


class InteractiveResearch:
    """Keep the v1 Python entry point while delegating interaction to the v2 TUI."""

    def __init__(
        self,
        root: Path,
        settings: Settings,
        provider: ModelProvider,
        console: Console | None = None,
    ) -> None:
        self.root = root
        self.settings = settings
        self.provider = provider
        self.console = console or Console()

    def _require_terminal(self) -> None:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError(
                "interactive mode requires a TTY; use `ragdoll investigations`, `show`, "
                "or `export` for non-interactive workflows"
            )

    def start(self, prompt: str | None = None) -> Investigation:
        self._require_terminal()
        result = RagdollApp(
            self.root,
            self.settings,
            self.provider,
            topic=prompt,
        ).run()
        if result is None:
            raise ValueError("the investigation ended before it was created")
        return result

    def resume(self, investigation: Investigation) -> Investigation:
        self._require_terminal()
        result = RagdollApp(
            self.root,
            self.settings,
            self.provider,
            investigation=investigation,
        ).run()
        return result or investigation
