#!/usr/bin/env python3
"""Generate the favicon pack for nutrientchart.com.

The mark is a leaf over three rising bars (a nutrient chart) on the site's dark header green.
Output lands in favicon/ (committed); build.py copies it to the site root.
Needs rsvg-convert and ImageMagick (brew install librsvg imagemagick):

    python3 scripts/make_favicons.py
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "favicon"
DARK, GREEN, LIGHT, TEAL = "#0f2a1f", "#34c177", "#e7f3ec", "#38bdf8"


def svg(small: bool = False, full_bleed: bool = False) -> str:
    bg = (f'<rect width="512" height="512" fill="{DARK}"/>' if full_bleed
          else f'<rect width="512" height="512" rx="104" fill="{DARK}"/>')
    if small:
        bars = (f'<rect x="92" y="300" width="88" height="140" rx="18" fill="{LIGHT}" opacity=".55"/>'
                f'<rect x="212" y="220" width="88" height="220" rx="18" fill="{LIGHT}" opacity=".8"/>'
                f'<rect x="332" y="120" width="88" height="320" rx="18" fill="{GREEN}"/>')
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{bg}{bars}</svg>\n'
    bars = (f'<rect x="96" y="312" width="76" height="120" rx="16" fill="{LIGHT}" opacity=".5"/>'
            f'<rect x="218" y="248" width="76" height="184" rx="16" fill="{LIGHT}" opacity=".75"/>'
            f'<rect x="340" y="176" width="76" height="256" rx="16" fill="{GREEN}"/>')
    leaf = (f'<path d="M120 236 C120 140 200 72 318 68 C322 184 254 258 150 262 C140 262 128 254 120 236 Z" fill="{GREEN}"/>'
            f'<path d="M136 252 C180 196 236 150 300 96" stroke="{DARK}" stroke-width="16" stroke-linecap="round" fill="none"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{bg}{bars}{leaf}</svg>\n'


def png(src: Path, size: int, dest: Path) -> None:
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(dest), str(src)], check=True)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "favicon.svg").write_text(svg())
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "small.svg").write_text(svg(small=True))
        (t / "bleed.svg").write_text(svg(full_bleed=True))
        for size in (16, 32, 48):
            png(t / "small.svg" if size < 48 else OUT / "favicon.svg", size, t / f"{size}.png")
        shutil.copy(t / "16.png", OUT / "favicon-16x16.png")
        shutil.copy(t / "32.png", OUT / "favicon-32x32.png")
        subprocess.run(["magick", str(t / "16.png"), str(t / "32.png"), str(t / "48.png"), str(OUT / "favicon.ico")], check=True)
        png(t / "bleed.svg", 180, OUT / "apple-touch-icon.png")
    png(OUT / "favicon.svg", 192, OUT / "favicon-192.png")
    png(OUT / "favicon.svg", 512, OUT / "favicon-512.png")
    (OUT / "site.webmanifest").write_text(json.dumps({
        "name": "NutrientChart", "short_name": "NutrientChart",
        "icons": [{"src": "/favicon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/favicon-512.png", "sizes": "512x512", "type": "image/png"}],
        "theme_color": DARK, "background_color": "#f7f8f6", "display": "browser"}, indent=2) + "\n")
    for p in sorted(OUT.iterdir()):
        print(f"{p.name:24s} {p.stat().st_size:7d} bytes")


if __name__ == "__main__":
    main()
