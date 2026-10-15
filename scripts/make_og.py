#!/usr/bin/env python3
"""Generate the 1200x630 social preview image (og:image) for nutrientchart.com.

Same mark and colours as the favicon: leaf and bars on the dark header green, wordmark, tagline and a row of
%DV bars. Output: static/og-image.png (committed). Needs rsvg-convert (brew install librsvg):

    python3 scripts/make_og.py
"""
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "og-image.png"
DARK, GREEN, LIGHT, MUTED, TRACK = "#0f2a1f", "#34c177", "#e7f3ec", "#9fb8aa", "#1f3a2c"
FONT = "Helvetica Neue, Helvetica, Arial, sans-serif"
BARS = [("Potassium", 23), ("Magnesium", 19), ("Vitamin C", 112), ("Fiber", 33)]


def svg() -> str:
    mark = ('<g transform="translate(90,150) scale(0.62)">'
            f'<rect x="96" y="312" width="76" height="120" rx="16" fill="{LIGHT}" opacity=".5"/>'
            f'<rect x="218" y="248" width="76" height="184" rx="16" fill="{LIGHT}" opacity=".75"/>'
            f'<rect x="340" y="176" width="76" height="256" rx="16" fill="{GREEN}"/>'
            f'<path d="M120 236 C120 140 200 72 318 68 C322 184 254 258 150 262 C140 262 128 254 120 236 Z" fill="{GREEN}"/>'
            f'<path d="M136 252 C180 196 236 150 300 96" stroke="{DARK}" stroke-width="16" stroke-linecap="round" fill="none"/></g>')
    bars = []
    for i, (name, v) in enumerate(BARS):
        y = 372 + i * 46
        w = min(300, v * 3)
        bars.append(f'<text x="470" y="{y + 15}" font-size="22" fill="{MUTED}">{name}</text>'
                    f'<rect x="640" y="{y}" width="300" height="18" rx="9" fill="{TRACK}"/>'
                    f'<rect x="640" y="{y}" width="{w}" height="18" rx="9" fill="{GREEN}"/>'
                    f'<text x="960" y="{y + 15}" font-size="20" fill="{LIGHT}">{v}% DV</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" font-family="{FONT}">'
            f'<rect width="1200" height="630" fill="{DARK}"/>'
            f'<rect y="612" width="1200" height="18" fill="{GREEN}"/>{mark}'
            f'<text x="470" y="220" font-size="84" font-weight="800" fill="#fff" letter-spacing="-2">Nutrient'
            f'<tspan fill="{GREEN}">Chart</tspan></text>'
            f'<text x="472" y="278" font-size="30" fill="{LIGHT}">Foods ranked by nutrient, per serving. USDA data.</text>'
            + "".join(bars) +
            f'<text x="472" y="585" font-size="24" fill="{MUTED}">nutrientchart.com</text></svg>\n')


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "og.svg"
        src.write_text(svg())
        subprocess.run(["rsvg-convert", "-w", "1200", "-h", "630", "-o", str(OUT), str(src)], check=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
