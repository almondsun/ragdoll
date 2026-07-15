"""Scrollback-safe patchwork-cat terminal companion."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

WELCOME = r"""
   /\_/\      .----------------.
  ( o.o )  __/  curious minds   |
   > ^ <  /__   leave a trail.  |
  /|_✕_|\/   '-----------------'
   /   \      RAGdoll
""".strip("\n")

FRAMES = {
    "planning": [r" /\_/\  ?", r" /\_/\  ??", r" /\_/\  ???"],
    "searching": [r" /\_/\  ≋", r" /\_/\  ≋≋", r" /\_/\  ≋≋≋"],
    "staging": [r" /\_/\  [·  ]", r" /\_/\  [·· ]", r" /\_/\  [···]"],
    "success": [r" /\_/\  ✓", r" /\_/\  ✓✓"],
    "error": [r" /\_/\  !", r" /\_/\  !!"],
}


class Mascot:
    def __init__(self, console: Console, enabled: bool = True) -> None:
        self.console = console
        self.enabled = enabled and sys.stdout.isatty() and not os.getenv("NO_COLOR")

    def welcome(self) -> None:
        self.console.print(Text(WELCOME, style="bold #2aa198"))

    @contextmanager
    def activity(self, state: str, message: str) -> Iterator[None]:
        if not self.enabled:
            self.console.print(f"[dim]• {message}[/dim]")
            yield
            return
        frames = FRAMES.get(state, FRAMES["planning"])
        stop = threading.Event()
        live = Live(console=self.console, transient=True, refresh_per_second=8)

        def animate() -> None:
            index = 0
            while not stop.wait(0.22):
                art = Text(frames[index % len(frames)], style="bold #b87333")
                live.update(Group(art, Text(message, style="dim")), refresh=True)
                index += 1

        live.start()
        thread = threading.Thread(target=animate, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=1)
            live.stop()

    def result(self, message: str, success: bool = True) -> None:
        symbol = "✓" if success else "!"
        style = "green" if success else "red"
        self.console.print(f"[{style}]{symbol}[/{style}] {message}")
