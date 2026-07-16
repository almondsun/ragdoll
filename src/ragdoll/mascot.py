"""The minimal M2 cat identity for RAGdoll's terminal experience."""

from __future__ import annotations

from typing import Literal

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from . import __version__

MascotPhase = Literal["welcome", "idle", "planning", "searching", "staging", "success", "error"]

CYAN = "#56cfe1"
VIOLET = "#9b5de5"
CORAL = "#ff6b6b"
CREAM = "#fff3c4"

_OPEN = ("▲▲ ", "•ᴗ•")
_EAR_LEFT = ("▴▲ ", "•ᴗ•")
_EAR_RIGHT = ("▲▴ ", "•ᴗ•")
_BLINK = ("▲▲ ", "─ᴗ─")
_LOOK_LEFT = ("▲▲ ", "•ᴗ·")
_LOOK_RIGHT = ("▲▲ ", "·ᴗ•")
_PAW_LEFT = ("▴▲ ", "•ᴗ─")
_PAW_RIGHT = ("▲▴ ", "─ᴗ•")
_SMILE = ("▲▲ ", "•‿•")
_CONCERNED = ("▾▾ ", "•_•")

SPRITE_FRAMES: dict[MascotPhase, tuple[tuple[str, str], ...]] = {
    "welcome": (_OPEN, _EAR_LEFT, _OPEN, _BLINK),
    "idle": (_OPEN, _EAR_LEFT, _OPEN, _EAR_RIGHT, _OPEN, _BLINK, _BLINK, _OPEN),
    "planning": (_OPEN, _EAR_LEFT, _OPEN, _EAR_RIGHT),
    "searching": (_LOOK_LEFT, _OPEN, _LOOK_RIGHT, _OPEN),
    "staging": (_PAW_LEFT, _OPEN, _PAW_RIGHT, _OPEN),
    "success": (_SMILE, _OPEN, _SMILE, _OPEN),
    "error": (_CONCERNED, _OPEN, _CONCERNED, _OPEN),
}


def sprite_rows(phase: MascotPhase = "idle", frame: int = 0) -> tuple[str, str]:
    """Return one fixed-size sprite frame, wrapping to keep every phase loopable."""
    frames = SPRITE_FRAMES[phase]
    return frames[frame % len(frames)]


def frame_count(phase: MascotPhase) -> int:
    """Return the deterministic frame count for one phase loop."""
    return len(SPRITE_FRAMES[phase])


def _sprite_text(phase: MascotPhase, frame: int, *, color: bool) -> Text:
    rendered = Text()
    for row_index, row in enumerate(sprite_rows(phase, frame)):
        line = Text(row, style=f"bold {CYAN}" if color else "bold")
        if color:
            if row_index == 0:
                line.stylize(f"bold {VIOLET}", 0, 1)
            else:
                line.stylize(f"bold {CREAM}", 0, 1)
                line.stylize(f"bold {CORAL}", 1, 2)
                line.stylize(f"bold {CREAM}", 2, 3)
        rendered.append_text(line)
        if row_index == 0:
            rendered.append("\n")
    return rendered


def mascot_renderable(
    *, phase: MascotPhase = "welcome", frame: int = 0, color: bool = True
) -> RenderableType:
    """Return the two-row M2 cat and welcome wordmark."""
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
    """Return the persistent two-row companion and current application status."""
    rail = Table.grid(padding=(0, 2))
    rail.add_column(no_wrap=True)
    rail.add_column(vertical="middle")
    status = Text(message, style="dim")
    if phase in {"welcome", "idle"}:
        status.append("\n● ready", style=f"bold {CYAN}" if color else "bold")
    elif phase == "success":
        status.append("\n✓ complete", style=f"bold {CYAN}" if color else "bold")
    elif phase == "error":
        status.append("\n! stopped", style=f"bold {CORAL}" if color else "bold")
    else:
        status.append("\n● working", style=f"bold {CORAL}" if color else "bold")
    rail.add_row(_sprite_text(phase, frame, color=color), status)
    return rail


def pixel_widths() -> set[int]:
    """Expose all row widths for deterministic layout tests."""
    return {len(row) for frames in SPRITE_FRAMES.values() for frame in frames for row in frame}


def pixel_heights() -> set[int]:
    """Expose all frame heights for deterministic layout tests."""
    return {len(frame) for frames in SPRITE_FRAMES.values() for frame in frames}
