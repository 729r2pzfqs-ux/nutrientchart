"""Inline SVG charts for nutrientchart.com. Colours come from CSS variables so they follow the theme."""
from __future__ import annotations

from html import escape


def compare_bars(a_name: str, b_name: str, rows: list[dict]) -> str:
    """Grouped horizontal bars of %DV per serving for two foods. rows: [{name, a_dv, b_dv}] (max ~12)."""
    rows = [r for r in rows if r.get("a_dv") is not None and r.get("b_dv") is not None][:12]
    if not rows:
        return ""
    w, left, rh, top = 720, 200, 44, 34
    h = top + rh * len(rows) + 10
    mx = max(100.0, max(max(r["a_dv"], r["b_dv"]) for r in rows))
    mx = min(mx, 300.0)
    scale = (w - left - 70) / mx
    out = [f'<svg class="chart compare" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="{escape(a_name)} vs {escape(b_name)}: percent of Daily Value per serving">']
    out.append(f'<text x="{left}" y="16" class="lg" font-size="13"><tspan fill="var(--c-a)" font-weight="700">■ {escape(a_name)}</tspan>'
               f'<tspan dx="14" fill="var(--c-b)" font-weight="700">■ {escape(b_name)}</tspan></text>')
    for i, r in enumerate(rows):
        y = top + i * rh
        out.append(f'<text x="{left - 10}" y="{y + 25}" text-anchor="end" font-size="13">{escape(r["name"])}</text>')
        for j, (v, cls) in enumerate(((r["a_dv"], "var(--c-a)"), (r["b_dv"], "var(--c-b)"))):
            bw = max(2.0, min(v, mx) * scale)
            yy = y + 6 + j * 16
            out.append(f'<rect x="{left}" y="{yy}" width="{bw:.1f}" height="13" rx="4" fill="{cls}"/>')
            out.append(f'<text x="{left + bw + 6:.1f}" y="{yy + 11}" font-size="12" class="mu">{v:.0f}%</text>')
    x100 = left + 100 * scale
    out.append(f'<line x1="{x100:.1f}" x2="{x100:.1f}" y1="{top - 4}" y2="{h - 6}" class="grid" stroke-dasharray="3 3"/>')
    out.append(f'<text x="{x100:.1f}" y="{h - 1}" font-size="11" text-anchor="middle" class="mu">100% DV</text>')
    out.append("</svg>")
    return "".join(out)


def macro_donut(protein_kcal: float, fat_kcal: float, carb_kcal: float, label_kcal: float | None = None) -> str:
    """Calorie split donut (shares by 4-9-4 Atwater factors; the centre shows USDA's calorie value). '' when no calories."""
    total = protein_kcal + fat_kcal + carb_kcal
    if total <= 0:
        return ""
    shown = label_kcal if label_kcal is not None else total
    import math
    r, cx, cy, sw = 42, 60, 60, 16
    circ = 2 * math.pi * r
    out = [f'<svg class="chart donut" viewBox="0 0 120 120" width="120" height="120" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Calories from protein {protein_kcal / total:.0%}, fat {fat_kcal / total:.0%}, carbohydrate {carb_kcal / total:.0%}">']
    offset = 0.0
    for v, col in ((protein_kcal, "var(--c-a)"), (fat_kcal, "var(--c-b)"), (carb_kcal, "var(--accent-2)")):
        if v <= 0:
            continue
        seg = circ * v / total
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{col}" stroke-width="{sw}" '
                   f'stroke-dasharray="{seg:.2f} {circ - seg:.2f}" stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>')
        offset += seg
    out.append(f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="15" font-weight="700">{shown:.0f}</text>')
    out.append(f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" font-size="9" class="mu">kcal</text></svg>')
    return "".join(out)


def rank_bars(rows: list[dict], unit: str, key: str = "amount", label_key: str = "name", top: int = 10) -> str:
    """Horizontal bar chart of the top N rows of a ranking."""
    rows = rows[:top]
    if not rows:
        return ""
    w, left, rh = 720, 230, 30
    h = rh * len(rows) + 8
    mx = max(r[key] for r in rows) or 1
    scale = (w - left - 90) / mx
    out = [f'<svg class="chart rank" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Top {len(rows)} ranked foods">']
    for i, r in enumerate(rows):
        y = i * rh
        name = r.get(label_key) or r["name"]
        if len(name) > 30:
            name = name[:29] + "…"
        out.append(f'<text x="{left - 10}" y="{y + 19}" text-anchor="end" font-size="13">{escape(name)}</text>')
        bw = max(2.0, r[key] * scale)
        out.append(f'<rect x="{left}" y="{y + 6}" width="{bw:.1f}" height="17" rx="5" fill="var(--accent)" opacity="{1 - i * 0.05:.2f}"/>')
        val = f"{r[key]:,.0f}" if r[key] >= 10 else f"{r[key]:.1f}" if r[key] >= 1 else f"{r[key]:.2f}"
        out.append(f'<text x="{left + bw + 6:.1f}" y="{y + 19}" font-size="12" class="mu">{val} {escape(unit)}</text>')
    out.append("</svg>")
    return "".join(out)
