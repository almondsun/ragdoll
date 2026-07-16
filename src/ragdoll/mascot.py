"""Unicode pixel interpretation of the A3 RAGdoll mascot."""

# The stitched X eyes intentionally use a box-drawing glyph.
# ruff: noqa: RUF001

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

PIXEL_ROWS = (
    "       ▄▄▄▄▄▄▄       ",
    "    ▄███████████▄    ",
    "   ███▄███████▄███   ",
    "  ██  ╳  ███  ╳  ██  ",
    "  ██▄▄▄▄▄███▄▄▄▄▄██  ",
    "   █████▄   ▄█████   ",
    "     ▀███▄▄▄███▀     ",
    "       ▄████▄        ",
    "     ▄███▀▀███▄      ",
    "    ███▀  ●  ▀███    ",
    "    ▀▀▀       ▀▀▀    ",
)

ACTIVITY_FRAMES: dict[str, tuple[str, ...]] = {
    "planning": ("╳─╳  ◌", "╳─╳  ◔", "╳─╳  ◑", "╳─╳  ◕"),
    "searching": ("╳─╳  ≋", "╳─╳  ≋≋", "╳─╳  ≋≋≋"),
    "staging": ("╳─╳  [·  ]", "╳─╳  [·· ]", "╳─╳  [···]"),
    "success": ("╳‿╳  ✓",),
    "error": ("╳︵╳  !",),
}


def mascot_renderable(*, color: bool = True, blink: bool = False) -> RenderableType:
    """Return a terminal-safe, fixed-width mascot and wordmark."""
    style = "bold #2aa198" if color else "bold"
    rows: tuple[str, ...] = PIXEL_ROWS
    if blink:
        rows = tuple(row.replace("╳", "━") for row in rows)
    body = Text("\n".join(rows), style=style, justify="center")
    title = Text("RAGdoll 2.0", style="bold #b87333" if color else "bold", justify="center")
    subtitle = Text(
        "research, with receipts",
        style="italic dim",
        justify="center",
    )
    return Group(body, title, subtitle)


def activity_frame(state: str, index: int, *, color: bool = True) -> Text:
    frames = ACTIVITY_FRAMES.get(state, ACTIVITY_FRAMES["planning"])
    style = "bold #b87333" if color else "bold"
    return Text(frames[index % len(frames)], style=style)


def pixel_widths() -> set[int]:
    """Expose row widths for deterministic layout tests."""
    return {len(row) for row in PIXEL_ROWS}
