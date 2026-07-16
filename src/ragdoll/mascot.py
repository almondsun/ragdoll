"""Compact block-pixel cat identity for the RAGdoll terminal experience."""

from __future__ import annotations

from typing import Literal

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from . import __version__

MascotPhase = Literal["welcome", "planning", "searching", "staging", "success", "error"]

CYAN = "#56cfe1"
VIOLET = "#9b5de5"
CORAL = "#ff6b6b"
CREAM = "#fff3c4"
FRAME_COUNT = 3

_OPEN = (
    " ▄█▄   ▄█▄ ",
    "███████████",
    "██ ●   ● ██",
    " ███ ▴ ███ ",
    "   █████▄  ",
    "  ██ ● ██ █",
)
_BLINK = (*_OPEN[:2], "██ ━   ━ ██", *_OPEN[3:])
_EAR_TWITCH = (" ▄█▀   ▄█▄ ", *_OPEN[1:])
_TAIL_LEFT = (*_OPEN[:4], "  ▄█████   ", " █ ██ ● ██ ")
_PAW_UP = (*_OPEN[:5], "  █▀ ● ██ █")
_SUCCESS = ("✦▄█▄   ▄█▄ ", *_OPEN[1:4], "   █████ █ ", _OPEN[5])
_EARS_DOWN = (" ▀█▄   ▄█▀ ", *_OPEN[1:])

SPRITE_FRAMES: dict[MascotPhase, tuple[tuple[str, ...], ...]] = {
    "welcome": (_OPEN, _BLINK, _OPEN),
    "planning": (_OPEN, _EAR_TWITCH, _OPEN),
    "searching": (_OPEN, _TAIL_LEFT, _OPEN),
    "staging": (_OPEN, _PAW_UP, _OPEN),
    "success": (_OPEN, _SUCCESS, _SUCCESS),
    "error": (_OPEN, _EARS_DOWN, _EARS_DOWN),
}


def sprite_rows(phase: MascotPhase = "welcome", frame: int = 0) -> tuple[str, ...]:
    """Return one fixed-size sprite frame, clamping one-shot animations at the final pose."""
    frames = SPRITE_FRAMES[phase]
    return frames[min(max(frame, 0), len(frames) - 1)]


def _sprite_text(phase: MascotPhase, frame: int, *, color: bool) -> Text:
    rendered = Text()
    for row_index, row in enumerate(sprite_rows(phase, frame)):
        line = Text(row, style=f"bold {CYAN}" if color else "bold")
        if color:
            if row_index == 0:
                line.stylize(f"bold {VIOLET}", 1, 4)
            for marker in ("●", "━"):
                start = 0
                while (position := row.find(marker, start)) >= 0:
                    line.stylize(f"bold {CREAM}", position, position + 1)
                    start = position + 1
            if "▴" in row:
                position = row.index("▴")
                line.stylize(f"bold {CORAL}", position, position + 1)
            if row_index == 5 and "●" in row:
                position = row.index("●")
                line.stylize(f"bold {CORAL}", position, position + 1)
            if "✦" in row:
                position = row.index("✦")
                line.stylize(f"bold {CREAM}", position, position + 1)
        rendered.append_text(line)
        if row_index < len(_OPEN) - 1:
            rendered.append("\n")
    return rendered


def mascot_renderable(
    *, phase: MascotPhase = "welcome", frame: int = 0, color: bool = True
) -> RenderableType:
    """Return the compact cat and wordmark used for the welcome cameo."""
    lockup = Table.grid(padding=(0, 2))
    lockup.add_column(no_wrap=True)
    lockup.add_column(vertical="middle")
    words = Text()
    words.append(f"RAGdoll {__version__}\n", style=f"bold {VIOLET}" if color else "bold")
    words.append("research, with receipts", style="italic dim")
    lockup.add_row(_sprite_text(phase, frame, color=color), words)
    return lockup


def activity_renderable(
    phase: MascotPhase, frame: int, message: str, *, color: bool = True
) -> RenderableType:
    """Return a transient phase cameo with a stable textual progress signal."""
    cameo = Table.grid(padding=(0, 2))
    cameo.add_column(no_wrap=True)
    cameo.add_column(vertical="middle")
    status = Text(message, style="dim")
    status.append("\n● working", style=f"bold {CORAL}" if color else "bold")
    cameo.add_row(_sprite_text(phase, frame, color=color), status)
    return cameo


def pixel_widths() -> set[int]:
    """Expose all row widths for deterministic layout tests."""
    return {len(row) for frames in SPRITE_FRAMES.values() for frame in frames for row in frame}


def pixel_heights() -> set[int]:
    """Expose all frame heights for deterministic layout tests."""
    return {len(frame) for frames in SPRITE_FRAMES.values() for frame in frames}
