"""Render the public SVG and PNG assets from the terminal cat's canonical grid."""

# The SVG templates are intentionally kept as readable source markup.
# ruff: noqa: E501

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ragdoll.mascot import CORAL, CREAM, CYAN, VIOLET, sprite_rows

INK = "#172a3a"
CANVAS = "#0f141b"


def _pixel_glyph(glyph: str, x: float, y: float, size: float, fill: str) -> str:
    if glyph == "█":
        return f'<rect x="{x:g}" y="{y:g}" width="{size:g}" height="{size:g}" fill="{fill}"/>'
    if glyph == "▄":
        return (
            f'<rect x="{x:g}" y="{y + size / 2:g}" width="{size:g}" '
            f'height="{size / 2:g}" fill="{fill}"/>'
        )
    if glyph == "▀":
        return f'<rect x="{x:g}" y="{y:g}" width="{size:g}" height="{size / 2:g}" fill="{fill}"/>'
    if glyph == "●":
        return (
            f'<circle cx="{x + size / 2:g}" cy="{y + size / 2:g}" '
            f'r="{size * 0.23:g}" fill="{fill}"/>'
        )
    if glyph == "▴":
        return (
            f'<path d="M{x + size / 2:g} {y + size * 0.24:g} '
            f"L{x + size * 0.76:g} {y + size * 0.7:g} "
            f'H{x + size * 0.24:g}Z" fill="{fill}"/>'
        )
    if glyph == "━":
        return (
            f'<rect x="{x + size * 0.2:g}" y="{y + size * 0.44:g}" '
            f'width="{size * 0.6:g}" height="{size * 0.12:g}" fill="{fill}"/>'
        )
    if glyph == "✦":
        return (
            f'<path d="M{x + size / 2:g} {y:g} L{x + size * 0.62:g} {y + size * 0.38:g} '
            f"L{x + size:g} {y + size / 2:g} L{x + size * 0.62:g} {y + size * 0.62:g} "
            f"L{x + size / 2:g} {y + size:g} L{x + size * 0.38:g} {y + size * 0.62:g} "
            f'L{x:g} {y + size / 2:g} L{x + size * 0.38:g} {y + size * 0.38:g}Z" '
            f'fill="{fill}"/>'
        )
    raise ValueError(f"unsupported mascot glyph: {glyph!r}")


def _cat_group(x: float, y: float, cell: float) -> str:
    pieces = ['<g aria-label="Seated block-pixel cat" shape-rendering="crispEdges">']
    for row_index, row in enumerate(sprite_rows("welcome", 2)):
        for column_index, glyph in enumerate(row):
            if glyph == " ":
                continue
            fill = CYAN
            if row_index == 0 and 1 <= column_index <= 3:
                fill = VIOLET
            elif glyph in {"●", "━"}:
                fill = CREAM
            if glyph == "▴" or (row_index == 5 and glyph == "●"):
                fill = CORAL
            pieces.append(
                _pixel_glyph(glyph, x + column_index * cell, y + row_index * cell, cell, fill)
            )
    pieces.append("</g>")
    return "\n    ".join(pieces)


def mascot_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-labelledby="title desc">
  <title id="title">RAGdoll block-pixel research cat</title>
  <desc id="desc">A friendly seated cyan cat with a violet fabric ear and coral collar tag.</desc>
  <rect width="512" height="512" rx="96" fill="{CANVAS}"/>
  {_cat_group(69, 154, 34)}
</svg>
"""


def social_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" role="img" aria-labelledby="title desc">
  <title id="title">RAGdoll</title>
  <desc id="desc">A block-pixel research cat beside RAGdoll's explainable scholarly research wordmark.</desc>
  <rect width="1280" height="640" fill="{CANVAS}"/>
  <rect x="64" y="96" width="496" height="448" rx="72" fill="{INK}" stroke="{VIOLET}" stroke-width="4"/>
  {_cat_group(92, 196, 40)}
  <text x="620" y="274" fill="{CREAM}" font-size="108" font-family="ui-monospace, monospace" font-weight="700">RAGdoll</text>
  <text x="625" y="350" fill="{CYAN}" font-size="34" font-family="ui-sans-serif, sans-serif">Research, with receipts.</text>
  <text x="625" y="416" fill="#d9d5e3" font-size="26" font-family="ui-sans-serif, sans-serif">Explainable scholarly research from your terminal.</text>
  <circle cx="630" cy="474" r="8" fill="{CORAL}"/>
  <text x="652" y="483" fill="#d9d5e3" font-size="22" font-family="ui-monospace, monospace">plan · search · stage · understand</text>
</svg>
"""


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    assets = root / "docs" / "assets"
    mascot = assets / "ragdoll-mascot.svg"
    social = assets / "ragdoll-social.svg"
    mascot.write_text(mascot_svg(), encoding="utf-8")
    social.write_text(social_svg(), encoding="utf-8")
    converter = shutil.which("rsvg-convert")
    if converter is None:
        raise SystemExit("rsvg-convert is required to regenerate PNG brand assets")
    subprocess.run([converter, str(mascot), "-o", str(assets / "ragdoll-mascot.png")], check=True)
    subprocess.run([converter, str(social), "-o", str(assets / "ragdoll-social.png")], check=True)


if __name__ == "__main__":
    main()
