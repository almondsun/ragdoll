"""Render public SVG and PNG assets from the terminal M2 identity."""

# The SVG templates are intentionally kept as readable source markup.
# ruff: noqa: E501

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ragdoll.mascot import CORAL, CREAM, CYAN, VIOLET

INK = "#172a3a"
CANVAS = "#0f141b"


def _m2_group(x: float, y: float, size: float) -> str:
    """Render the terminal's `▲▲ / •ᴗ•` mark without depending on an SVG font."""
    eye_radius = size * 0.16
    stroke = size * 0.12
    return f"""<g aria-label="Minimal M2 research cat" stroke-linecap="round" stroke-linejoin="round">
    <path d="M{x:g} {y + size:g} L{x + size / 2:g} {y:g} L{x + size:g} {y + size:g}Z" fill="{VIOLET}"/>
    <path d="M{x + size:g} {y + size:g} L{x + size * 1.5:g} {y:g} L{x + size * 2:g} {y + size:g}Z" fill="{CYAN}"/>
    <circle cx="{x + size * 0.35:g}" cy="{y + size * 1.55:g}" r="{eye_radius:g}" fill="{CREAM}"/>
    <circle cx="{x + size * 1.65:g}" cy="{y + size * 1.55:g}" r="{eye_radius:g}" fill="{CREAM}"/>
    <path d="M{x + size * 0.72:g} {y + size * 1.62:g} Q{x + size:g} {y + size * 2.04:g} {x + size * 1.28:g} {y + size * 1.62:g}" fill="none" stroke="{CORAL}" stroke-width="{stroke:g}"/>
  </g>"""


def mascot_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-labelledby="title desc">
  <title id="title">RAGdoll M2 research cat</title>
  <desc id="desc">A minimal two-row cat face with violet and cyan ears, cream eyes, and a coral smile.</desc>
  <rect width="512" height="512" rx="96" fill="{CANVAS}"/>
  {_m2_group(106, 136, 150)}
</svg>
"""


def social_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" role="img" aria-labelledby="title desc">
  <title id="title">RAGdoll</title>
  <desc id="desc">The minimal M2 research cat beside RAGdoll's explainable scholarly research wordmark.</desc>
  <rect width="1280" height="640" fill="{CANVAS}"/>
  <rect x="64" y="96" width="496" height="448" rx="72" fill="{INK}" stroke="{VIOLET}" stroke-width="4"/>
  {_m2_group(154, 178, 158)}
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
