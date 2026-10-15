"""Render nutrientchart.com into docs/ (GitHub Pages).

    python3 build.py

Data: data/*.json (built by tools/build_data.py from the USDA FoodData Central CSVs in data/source/).
Templates: templates/*.html (Jinja2). Charts: svg.py. Every number and every generated sentence on the site
comes from data/; nothing is hand-written per food.

Pages: / , /foods-high-in/, /foods-high-in/<nutrient>/, /foods-high-in/<nutrient>/<group>/, /foods-low-in/<x>/,
/food/, /food/<slug>/, /food/<slug>/<nutrient>/, /compare/, /compare/<a>-vs-<b>/ (+ reverse redirect stubs),
/healthiest/, /healthiest/<category>/, /category/, /category/<group>/, /guide/, /guide/<slug>/, /about/,
/about/methodology/, /about/data-sources/, /privacy/, /terms/, 404. Plus sitemap.xml, robots.txt, ads.txt,
search-index.json, CNAME, favicons.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from statistics import median

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

import svg

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
SITE_URL = "https://nutrientchart.com"
DOMAIN = "nutrientchart.com"
SITE_NAME = "NutrientChart"
CONTACT_EMAIL = "info@nutrientchart.com"
OG_IMAGE = SITE_URL + "/static/og-image.png"      # 1200x630, scripts/make_og.py
ADSENSE_PUB = "ca-pub-5861928596436289"
GA_ID = ""                                        # GA4 measurement id (G-XXXXXXXXXX); tags are omitted while empty
AD_SLOTS: dict[str, str] = {}                     # AdSense slot ids; empty = auto ads only
TODAY = date.today()
DATA_UPDATED = "2026-10-15"   # last data/content change: dateModified, sitemap lastmod, "Updated" lines
PUBLISHED = "2026-10-15"      # site launch: datePublished
USDA_CITATION = "U.S. Department of Agriculture, Agricultural Research Service. FoodData Central, 2026. fdc.nal.usda.gov."

GROUP_SLUG_NAMES = {"fruits": "Fruits", "vegetables": "Vegetables", "legumes": "Legumes", "nuts-seeds": "Nuts and seeds",
                    "grains": "Grains", "fish-seafood": "Fish and seafood", "meat": "Meat and poultry",
                    "dairy-eggs": "Dairy and eggs", "fats-oils": "Fats and oils", "other": "Other foods"}
GROUP_SINGULAR = {"fruits": "fruit", "vegetables": "vegetable", "legumes": "legume", "nuts-seeds": "nut or seed",
                  "grains": "grain", "fish-seafood": "fish or seafood", "meat": "meat", "dairy-eggs": "dairy food or egg",
                  "fats-oils": "fat or oil", "other": "food"}
NUT_GROUP_NAMES = {"macros": "Macronutrients", "fats": "Fats", "minerals": "Minerals", "vitamins": "Vitamins",
                   "carotenoids": "Carotenoids", "other": "Other", "amino": "Amino acids"}


# ------------------------------------------------------------------ helpers
def load(name: str):
    return json.loads((DATA / name).read_text())


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def fmt(v, decimals: int = 1) -> str:
    """Number for display: '—' for None, thousands separators, no trailing zeros."""
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 100:
        return f"{v:,.0f}" if decimals <= 1 else f"{v:,.1f}".rstrip("0").rstrip(".")
    s = f"{v:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def pct(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}%" if v >= 10 else f"{v:.1f}%".replace(".0%", "%")


def fit_desc(d: str, n: int = 158) -> str:
    d = re.sub(r"\s+", " ", d).strip()
    if len(d) <= n:
        return d
    cut = d[:n]
    dot = cut.rfind(". ")
    return cut[:dot + 1] if dot >= 90 else cut[:n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def asset(name: str) -> str:
    h = hashlib.sha256((ROOT / "static" / name).read_bytes()).hexdigest()[:10]
    return f"/static/{name}?v={h}"


def lower_name(name: str) -> str:
    """'Greek yogurt (plain, nonfat)' -> 'Greek yogurt' lowercased unless it is a proper noun."""
    base = re.sub(r"\s*\(.*?\)", "", name).strip()
    return base if base[:1].isupper() and base.split()[0] in ("Greek", "Swiss", "Brazil", "Brussels", "Medjool") else base[0].lower() + base[1:]


def short_name(name: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", name).strip()


def nlow(name: str) -> str:
    """Nutrient name for running text: 'Vitamin C' -> 'vitamin C', 'Folate (DFE)' -> 'folate', 'Omega-3 (ALA+EPA+DHA)' -> 'omega-3'."""
    base = re.sub(r"\s*\(.*?\)", "", name).strip()
    return base[0].lower() + base[1:]


def level_word(dv: float | None) -> str | None:
    if dv is None:
        return None
    return "an excellent source" if dv >= 20 else "a good source" if dv >= 10 else None


def redirect_stub(target: str, label: str) -> str:
    url = SITE_URL + target
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{label}</title>'
            f'<link rel="canonical" href="{url}"><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={target}"></head>'
            f'<body><p>Moved to <a href="{target}">{label}</a>.</p></body></html>\n')


def faq_ld(faq: list[dict]) -> dict:
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": q["a"]}} for q in faq]}


def dataset_ld(name: str, desc: str, url: str) -> dict:
    return {"@context": "https://schema.org", "@type": "Dataset", "name": name, "description": desc, "url": url,
            "license": "https://creativecommons.org/publicdomain/zero/1.0/", "isAccessibleForFree": True,
            "creator": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
            "isBasedOn": {"@type": "Dataset", "name": "USDA FoodData Central", "url": "https://fdc.nal.usda.gov/",
                          "license": "https://creativecommons.org/publicdomain/zero/1.0/"},
            "dateModified": DATA_UPDATED}


def crumbs_ld(crumbs: list[tuple[str, str]]) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": label, "item": SITE_URL + href} for i, (href, label) in enumerate(crumbs)]}


# ------------------------------------------------------------------ site
class Site:
    def __init__(self):
        self.ndefs = load("nutrients.json")
        self.N = {n["key"]: n for n in self.ndefs["nutrients"]}
        self.foods = load("foods.json")
        self.F = {f["slug"]: f for f in self.foods}
        self.pool = load("pool.json")
        self.rankings = load("rankings.json")
        self.healthiest = load("healthiest.json")
        self.cats = load("categories.json")
        self.meta = load("meta.json")
        self.comps_cfg = json.loads((DATA / "curated" / "comparisons.json").read_text())
        self.answers_cfg = json.loads((DATA / "curated" / "answers.json").read_text())
        self.urls: list[tuple[str, float]] = []
        self.search: list[dict] = []
        self.guides: list[dict] = []
        self.rank_keys = self.ndefs["rank_order"]
        self.env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]),
                               trim_blocks=True, lstrip_blocks=True)
        self.env.filters.update(fmt=fmt, pct=pct, lower_name=lower_name, short=short_name, nlow=nlow)
        self.env.globals.update(site_name=SITE_NAME, site_url=SITE_URL, email=CONTACT_EMAIL, adsense_pub=ADSENSE_PUB,
                                ga_id=GA_ID, ad_slots=AD_SLOTS, og_image=OG_IMAGE, asset=asset, year_now=TODAY.year,
                                updated=DATA_UPDATED, N=self.N, group_names=GROUP_SLUG_NAMES, svg=svg, Markup=Markup,
                                rank_keys=self.rank_keys, meta=self.meta, nut_group_names=NUT_GROUP_NAMES,
                                usda_citation=USDA_CITATION)
        for f in self.foods:
            self.enrich_food(f)
        self.comps = [self.make_comparison(a, b) for a, b in self.comps_cfg if a in self.F and b in self.F]

    # ---------------------------------------------------------------- nutrient maths
    def per(self, n: dict, key: str, grams: float):
        v = n.get(key)
        return None if v is None else v * grams / 100.0

    def dv(self, key: str, amount):
        d = self.N[key].get("dv")
        return None if amount is None or not d else amount / d * 100.0

    def rows_for(self, n: dict, grams: float, keys: list[str] | None = None, sources: dict | None = None) -> list[dict]:
        rows = []
        for nd in self.ndefs["nutrients"]:
            if keys and nd["key"] not in keys:
                continue
            if nd["key"] not in n:
                continue
            amt = self.per(n, nd["key"], grams)
            rows.append({"key": nd["key"], "name": nd["name"], "unit": nd["unit"], "group": nd["group"],
                         "amount": amt, "dv": self.dv(nd["key"], amt), "decimals": nd.get("decimals", 1),
                         "src": (sources or {}).get(nd["key"]), "per100": n.get(nd["key"]),
                         "limit": nd.get("limit", False)})
        return rows

    def enrich_food(self, f: dict) -> None:
        g = f["serving"]["g"]
        f["kcal"] = self.per(f["n"], "energy", g)
        f["bases"] = [("serving", f["serving"]["short"] if not f["serving"].get("fallback") else "100 g", g), ("100 g", "100 g", 100.0)]
        if abs(g - 28.35) > 1 and f["group"] not in ("fats-oils",):
            f["bases"].append(("1 oz", "1 oz (28 g)", 28.35))
        f["tables"] = {b[0]: self.rows_for(f["n"], b[2], sources=f["sources"]) for b in f["bases"]}
        rows = f["tables"]["serving"]
        good = [r for r in rows if r["dv"] is not None and not r["limit"] and r["key"] not in ("energy", "carbs", "fat", "cholesterol")]
        good.sort(key=lambda r: -r["dv"])
        f["highlights"] = good[:6]
        f["excellent"] = [r for r in good if r["dv"] >= 20]
        f["good"] = [r for r in good if 10 <= r["dv"] < 20]
        f["low_kcal"] = f["kcal"] is not None and f["kcal"] < 40
        p, fa, c = (self.per(f["n"], k, g) or 0 for k in ("protein", "fat", "carbs"))
        f["donut"] = Markup(svg.macro_donut(p * 4, fa * 9, c * 4, f["kcal"]))
        tot = (p * 4 + fa * 9 + c * 4) or 1
        f["macro_pct"] = {"protein": p * 4 / tot * 100, "fat": fa * 9 / tot * 100, "carbs": c * 4 / tot * 100}
        f["answer"] = self.food_answer(f)
        f["url"] = f"/food/{f['slug']}/"
        f["appears"] = [(k, f["ranks"][k]) for k in self.rank_keys if k in f["ranks"]]
        f["appears"].sort(key=lambda t: (t[1]["all"] or 999, t[1]["group"] or 999))

    def food_answer(self, f: dict) -> str:
        n, g = f["n"], f["serving"]["g"]
        name = short_name(f["name"])
        serv = f["serving"]["short"] if not f["serving"].get("fallback") else "100 g"
        kcal = self.per(n, "energy", g)
        bits = []
        for k, lab in (("protein", "g protein"), ("fiber", "g fiber"), ("fat", "g fat"), ("carbs", "g carbohydrate")):
            v = self.per(n, k, g)
            if v is not None:
                bits.append(f"{fmt(v)} {lab}")
        s = f"{name} ({serv}, {g:g} g) has {fmt(kcal, 0)} calories, {', '.join(bits[:3])}."
        ex = [r for r in f["excellent"]][:3]
        gd = [r for r in f["good"]][:2]
        if ex:
            s += " It is an excellent source of " + ", ".join(f"{nlow(r['name'])} ({pct(r['dv'])} DV)" for r in ex)
            if gd:
                s += " and a good source of " + " and ".join(nlow(r["name"]) for r in gd)
            s += "."
        elif gd:
            s += " It is a good source of " + " and ".join(nlow(r["name"]) for r in gd) + "."
        else:
            s += " No single vitamin or mineral reaches 10% of the Daily Value per serving."
        return s

    # ---------------------------------------------------------------- comparisons
    COMPARE_KEYS = ["energy", "protein", "fat", "sat_fat", "mono", "poly", "omega3", "cholesterol", "carbs", "fiber", "sugars",
                    "calcium", "iron", "magnesium", "phosphorus", "potassium", "sodium", "zinc", "copper", "manganese", "selenium",
                    "vit_a", "vit_c", "vit_d", "vit_e", "vit_k", "thiamin", "riboflavin", "niacin", "b6", "folate", "b12", "choline"]
    CHART_KEYS = ["protein", "fiber", "potassium", "magnesium", "calcium", "iron", "zinc", "vit_c", "vit_a", "vit_k", "folate", "b12"]

    def make_comparison(self, sa: str, sb: str) -> dict:
        a, b = self.F[sa], self.F[sb]
        slug_a, slug_b = sorted([sa, sb])
        a, b = self.F[slug_a], self.F[slug_b]
        ga, gb = a["serving"]["g"], b["serving"]["g"]
        rows, wins_a, wins_b = [], [], []
        for k in self.COMPARE_KEYS:
            if k not in a["n"] or k not in b["n"]:
                continue
            nd = self.N[k]
            va, vb = self.per(a["n"], k, ga), self.per(b["n"], k, gb)
            pa, pb = a["n"][k], b["n"][k]
            higher_better = not nd.get("limit") and k not in ("energy", "cholesterol", "carbs", "sugars", "fat")
            win = None
            if pa != pb and max(pa, pb) > 0:
                ratio = max(pa, pb) / max(min(pa, pb), 1e-9)
                if ratio >= 1.15:
                    win = "a" if pa > pb else "b"
            rows.append({"key": k, "name": nd["name"], "unit": nd["unit"], "a": va, "b": vb, "a100": pa, "b100": pb,
                         "a_dv": self.dv(k, va), "b_dv": self.dv(k, vb), "win": win, "dec": nd.get("decimals", 1),
                         "good": higher_better})
            if higher_better and win == "a" and pa > 0 and (self.dv(k, va) or 0) >= 5:
                wins_a.append((k, pa / max(pb, 1e-9)))
            if higher_better and win == "b" and pb > 0 and (self.dv(k, vb) or 0) >= 5:
                wins_b.append((k, pb / max(pa, 1e-9)))
        wins_a.sort(key=lambda t: -t[1])
        wins_b.sort(key=lambda t: -t[1])

        def phrase(wins):
            out = []
            for k, r in wins[:4]:
                nm = nlow(self.N[k]["name"])
                out.append(f"{'over ' + str(int(r)) + '×' if r >= 2 and r < 50 else f'{r:.1f}×' if r < 2 else 'far'} the {nm}" if r < 50 else f"{nm} where the other has almost none")
            return out

        an, bn = short_name(a["name"]), short_name(b["name"])
        pa, pb = phrase(wins_a), phrase(wins_b)
        verdict = []
        if pa:
            verdict.append(f"{an} has {', '.join(pa[:3])} of {bn} per 100 g.")
        if pb:
            verdict.append(f"{bn} has {', '.join(pb[:3])} of {an}.")
        ka, kb = self.per(a["n"], "energy", 100), self.per(b["n"], "energy", 100)
        if ka and kb:
            lo, hi = (an, bn) if ka < kb else (bn, an)
            verdict.append(f"{lo} is lower in calories ({fmt(min(ka, kb), 0)} vs {fmt(max(ka, kb), 0)} kcal per 100 g).")
        chart_rows = [{"name": re.sub(r"\s*\(.*?\)", "", r["name"]), "a_dv": r["a_dv"], "b_dv": r["b_dv"]} for r in rows if r["key"] in self.CHART_KEYS]
        cid = f"{slug_a}-vs-{slug_b}"
        return {"id": cid, "a": a, "b": b, "title": f"{an} vs {bn}", "rows": rows, "verdict": verdict,
                "wins_a": len(wins_a), "wins_b": len(wins_b), "chart": Markup(svg.compare_bars(an, bn, chart_rows)),
                "same_group": a["group"] == b["group"]}

    # ---------------------------------------------------------------- render
    def render(self, template: str, path: str, title: str, description: str, *, priority: float = 0.5,
               crumbs=None, jsonld=None, is_404: bool = False, **ctx) -> None:
        assert len(title) <= 60, f"title too long ({len(title)}): {title}"
        description = fit_desc(description)
        ld = list(jsonld or [])
        if crumbs and len(crumbs) > 1:
            ld.append(crumbs_ld(crumbs))
        if path == "/":
            ld.append({"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": SITE_URL,
                       "potentialAction": {"@type": "SearchAction", "target": f"{SITE_URL}/?q={{search_term_string}}",
                                           "query-input": "required name=search_term_string"}})
            ld.append({"@context": "https://schema.org", "@type": "Organization", "name": SITE_NAME, "url": SITE_URL,
                       "logo": SITE_URL + "/favicon-512.png", "email": CONTACT_EMAIL})
        html = self.env.get_template(template).render(title=title, description=description, path=path, crumbs=crumbs,
                                                      jsonld=ld, is_404=is_404, **ctx)
        out = DOCS / path.lstrip("/")
        if not path.endswith(".html"):
            out = out / "index.html"
        write(out, html)
        if not is_404:
            self.urls.append((path, priority))

    # ---------------------------------------------------------------- pages
    def home(self):
        top = [self.rank_card(k) for k in self.rank_keys[:12]]
        popular = [self.F[s] for s in ("banana", "avocado", "spinach", "egg", "salmon", "oats", "almonds", "chicken-breast",
                                      "sweet-potato", "greek-yogurt", "lentils", "broccoli") if s in self.F]
        self.render("home.html", "/", "NutrientChart: Foods Ranked by Nutrient, per Serving",
                    f"Which foods are highest in potassium, magnesium, iron or vitamin D? {len(self.pool):,} whole foods from USDA "
                    f"FoodData Central ranked per serving, with %DV, nutrition facts and side-by-side comparisons.",
                    priority=1.0, top=top, popular=popular, comps=self.comps[:12], comps_n=len(self.comps), healthiest=self.healthiest,
                    cats=self.cats, pool_n=len(self.pool), food_n=len(self.foods), rank_n=len(self.rank_keys))

    def rank_card(self, key: str) -> dict:
        nd, r = self.N[key], self.rankings[key]
        top1 = r["all"][0]
        return {"key": key, "name": nd["name"], "slug": nd["slug"], "top": top1, "unit": nd["unit"], "n": len(r["all"]),
                "groups": list(r["groups"])}

    def ranking_pages(self):
        cards = [self.rank_card(k) for k in self.rank_keys]
        groups = {"Minerals": [c for c in cards if self.N[c["key"]]["group"] == "minerals"],
                  "Vitamins": [c for c in cards if self.N[c["key"]]["group"] == "vitamins"],
                  "Protein, fiber and fats": [c for c in cards if self.N[c["key"]]["group"] in ("macros", "fats")],
                  "Carotenoids and other": [c for c in cards if self.N[c["key"]]["group"] in ("carotenoids", "other")]}
        self.render("ranking_index.html", "/foods-high-in/", f"Foods High in Each Nutrient: {len(cards)} Ranked Lists",
                    f"{len(cards)} ranked lists of whole foods high in a vitamin, mineral or macronutrient, per common serving "
                    f"with %DV, from USDA data. Potassium, magnesium, iron, protein, fiber, vitamin D and more.",
                    crumbs=[("/", "Home"), ("/foods-high-in/", "Foods high in")], priority=0.9, groups=groups,
                    low=[(k, self.N[k]) for k in self.ndefs["low_pages"]])
        for key in self.rank_keys:
            self.ranking_page(key)
            for g in self.rankings[key]["groups"]:
                if key in self.ndefs["subpage_nutrients"]:
                    self.ranking_page(key, g)
        for key in self.ndefs["low_pages"]:
            self.ranking_page(key, low=True)
        self.render("ranking_index_low.html", "/foods-low-in/", "Foods Low in Sodium and Sugar: Ranked Lists",
                    "Whole foods lowest in sodium and lowest in sugar per serving, ranked from USDA data and sorted by nutrient density.",
                    crumbs=[("/", "Home"), ("/foods-low-in/", "Foods low in")], priority=0.6,
                    low=[(k, self.N[k], self.rankings["low_" + k]["all"][:5]) for k in self.ndefs["low_pages"]])

    def ranking_page(self, key: str, group: str | None = None, low: bool = False):
        nd = self.N[key]
        rk = ("low_" if low else "") + key
        R = self.rankings[rk]
        rows = R["groups"][group] if group else R["all"]
        unit = nd["unit"]
        nname = nd["name"]
        nshort = re.sub(r"\s*\(.*?\)", "", nname)
        nlow = nshort[0].lower() + nshort[1:]
        dvv = nd.get("dv")
        if low:
            slug_path = f"/foods-low-in/{nd['slug']}/"
            title = f"Foods Low in {nshort}: {len(rows)} Whole Foods Ranked"
            h1 = f"Foods low in {nlow}"
            crumbs = [("/", "Home"), ("/foods-low-in/", "Foods low in"), (slug_path, h1)]
        elif group:
            gname = GROUP_SLUG_NAMES[group]
            slug_path = f"/foods-high-in/{nd['slug']}/{group}/"
            title = f"{gname} High in {nshort}: Ranked per Serving"
            if len(title) > 60:
                title = f"{gname} High in {nshort} (Ranked)"
            h1 = f"{gname} high in {nlow}"
            crumbs = [("/", "Home"), ("/foods-high-in/", "Foods high in"), (f"/foods-high-in/{nd['slug']}/", f"Foods high in {nlow}"), (slug_path, gname)]
        else:
            slug_path = f"/foods-high-in/{nd['slug']}/"
            title = f"Foods High in {nshort}: Top {len(rows)} Ranked (per Serving)"
            if len(title) > 60:
                title = f"Foods High in {nshort}: Top {len(rows)} Ranked"
            h1 = f"Foods high in {nlow}"
            crumbs = [("/", "Home"), ("/foods-high-in/", "Foods high in"), (slug_path, h1)]
        t1, t2, t3 = rows[0], rows[1], rows[2]

        def amt(r):
            return f"{fmt(r['amount'], nd.get('decimals', 1))} {unit}"

        def dvs(r):
            return f" ({pct(r['dv'])} of the Daily Value)" if r.get("dv") is not None else ""

        scope = f"{GROUP_SLUG_NAMES[group].lower()}" if group else "whole foods"
        if low:
            intro = (f"{len(rows)} {scope} with the least {nlow} per serving, from USDA FoodData Central. Foods with none at all are "
                     f"listed first and sorted by overall nutrient density, so the most nutritious {nlow}-free foods lead.")
        else:
            intro = (f"{len(rows)} {scope} ranked by {nlow} per common serving, from USDA FoodData Central. "
                     f"{t1.get('short', t1['name'])} leads with {amt(t1)} per {t1['serving']}{dvs(t1)}, followed by {t2.get('short', t2['name'])} ({amt(t2)}) "
                     f"and {t3.get('short', t3['name'])} ({amt(t3)}).")
        # group sections (main page only)
        sections = []
        if not group and not low:
            for g, lst in R["groups"].items():
                sections.append({"slug": g, "name": GROUP_SLUG_NAMES[g], "rows": lst[:10], "n": len(lst),
                                 "has_page": key in self.ndefs["subpage_nutrients"]})
        faq = []
        if not low:
            faq.append({"q": f"Which food is highest in {nlow}?",
                        "a": f"Among {scope} in the USDA database, {t1['name']} has the most {nlow} per serving: {amt(t1)} per {t1['serving']}{dvs(t1)}. "
                             f"Per 100 g it contains {fmt(t1['per100'], nd.get('decimals', 1))} {unit}."})
            if not group:
                for g in ("fruits", "vegetables"):
                    if g in R["groups"]:
                        r0 = R["groups"][g][0]
                        faq.append({"q": f"Which {GROUP_SINGULAR[g]} has the most {nlow}?",
                                    "a": f"{r0['name']}, with {amt(r0)} per {r0['serving']}{dvs(r0)}. See the full list of {GROUP_SLUG_NAMES[g].lower()} high in {nlow} below."})
            if dvv:
                faq.append({"q": f"How much {nlow} do I need per day?",
                            "a": f"The FDA Daily Value used on Nutrition Facts labels is {fmt(dvv, 2)} {unit} of {nlow} for adults and children aged 4 and over. "
                                 f"Individual needs vary with age, sex, pregnancy and health conditions."})
                faq.append({"q": f"What counts as a food high in {nlow}?",
                            "a": f"FDA labeling rules call a food a 'good source' when one serving provides 10 to 19% of the Daily Value and 'high' or 'excellent' at 20% or more. "
                                 f"{sum(1 for r in rows if (r['dv'] or 0) >= 20)} of the {len(rows)} foods on this list reach 20% DV per serving."})
            else:
                faq.append({"q": f"Is there a Daily Value for {nlow}?",
                            "a": f"No. The FDA has not set a Daily Value for {nlow}, so this list shows {unit} per serving without a percentage. {nd.get('about', '')}"})
        else:
            faq.append({"q": f"Which foods have no {nlow}?",
                        "a": f"{', '.join(r['name'] for r in rows[:5])} and many other whole foods contain no measurable {nlow}. The list sorts {nlow}-free foods by overall nutrient density."})
            if dvv:
                faq.append({"q": f"What is the daily limit for {nlow}?", "a": f"The Daily Value is {fmt(dvv, 0)} {unit}; FDA guidance is to stay at or below it."})
        desc = intro if not group else f"{len(rows)} {scope} ranked by {nlow} per serving (USDA data). {t1.get('short', t1['name'])} leads with {amt(r=t1)}{dvs(t1)}, then {t2.get('short', t2['name'])} and {t3.get('short', t3['name'])}."
        ld = [faq_ld(faq), dataset_ld(f"{h1} (per serving)", f"{len(rows)} foods ranked by {nlow} per serving, derived from USDA FoodData Central.", SITE_URL + slug_path),
              {"@context": "https://schema.org", "@type": "ItemList", "name": h1, "numberOfItems": len(rows), "itemListOrder": "https://schema.org/ItemListOrderDescending",
               "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": r["name"],
                                    **({"url": SITE_URL + f"/food/{r['page']}/"} if r.get("page") else {})} for i, r in enumerate(rows[:25])]}]
        related = [k for k in self.rank_keys if k != key and self.N[k]["group"] == nd["group"]][:6] or [k for k in self.rank_keys if k != key][:6]
        answers = [(fk, self.F[fk]) for nk, fk in self.answers_cfg if nk == key and fk in self.F]
        chart = Markup(svg.rank_bars(rows, unit, label_key="short")) if not low else ""
        self.render("ranking.html", slug_path, title, desc, crumbs=crumbs, jsonld=ld, priority=0.9 if not group else 0.7,
                    nd=nd, key=key, rows=rows, intro=intro, h1=h1, sections=sections, faq=faq, related=related,
                    group=group, low=low, unit=unit, nlow=nlow, nshort=nshort, chart=chart, answers=answers,
                    all_groups=list(R["groups"]), subpages=key in self.ndefs["subpage_nutrients"] and not low)
        self.search.append({"t": h1[0].upper() + h1[1:], "u": slug_path, "d": "Ranked list", "k": f"{nshort} rich foods sources"})

    def food_pages(self):
        by_group = {}
        for f in sorted(self.foods, key=lambda f: f["name"].lower()):
            by_group.setdefault(f["group"], []).append(f)
        self.render("food_index.html", "/food/", f"Nutrition Facts for {len(self.foods)} Common Foods",
                    f"Full nutrition facts for {len(self.foods)} common foods: calories, protein, fiber, vitamins and minerals per serving "
                    f"and per 100 g with %DV, from USDA FoodData Central.", crumbs=[("/", "Home"), ("/food/", "Foods")],
                    priority=0.8, by_group=by_group)
        for f in self.foods:
            name = short_name(f["name"])
            title = f"{f['name']} Nutrition Facts: Calories, Protein, %DV"
            if len(title) > 60:
                title = f"{f['name']} Nutrition Facts and %DV"
            if len(title) > 60:
                title = f"{name} Nutrition Facts"
            same = [x for x in self.foods if x["group"] == f["group"] and x["slug"] != f["slug"]][:8]
            comps = [c for c in self.comps if f["slug"] in (c["a"]["slug"], c["b"]["slug"])]
            answers = [(nk, self.N[nk]) for nk, fk in self.answers_cfg if fk == f["slug"]]
            faq = self.food_faq(f)
            serv = f["serving"]["short"] if not f["serving"].get("fallback") else "100 g"
            g = f["serving"]["g"]
            nutri = {"@type": "NutritionInformation", "servingSize": f"{serv} ({g:g} g)"}
            for k, prop, unit in (("energy", "calories", "calories"), ("protein", "proteinContent", "g"), ("fat", "fatContent", "g"),
                                  ("sat_fat", "saturatedFatContent", "g"), ("carbs", "carbohydrateContent", "g"), ("fiber", "fiberContent", "g"),
                                  ("sugars", "sugarContent", "g"), ("sodium", "sodiumContent", "mg"), ("cholesterol", "cholesterolContent", "mg")):
                v = self.per(f["n"], k, g)
                if v is not None:
                    nutri[prop] = f"{fmt(v, 0 if k in ('energy', 'sodium', 'cholesterol') else 1)} {unit}"
            ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": title, "description": f["answer"], "url": SITE_URL + f["url"],
                   "datePublished": PUBLISHED, "dateModified": DATA_UPDATED, "isAccessibleForFree": True,
                   "publisher": {"@type": "Organization", "name": SITE_NAME, "logo": SITE_URL + "/favicon-512.png"},
                   "mainEntity": {"@type": "Thing", "name": f["name"], "description": f["desc"], "nutrition": nutri,
                                  "sameAs": f"https://fdc.nal.usda.gov/food-details/{f['fdc_id']}/nutrients"}},
                  faq_ld(faq)]
            self.render("food.html", f["url"], title, f["answer"] + " Full USDA nutrition facts per serving and per 100 g.",
                        crumbs=[("/", "Home"), ("/food/", "Foods")] + ([(f"/category/{f['group']}/", GROUP_SLUG_NAMES[f["group"]])] if f["group"] in self.meta["rank_groups"] else []) + [(f["url"], name)],
                        jsonld=ld, priority=0.8, f=f, same=same, comps=comps[:8], answers=answers, faq=faq)
            self.search.append({"t": f"{f['name']} nutrition facts", "u": f["url"], "d": GROUP_SLUG_NAMES[f["group"]], "k": f.get("aliases", "")})
            for nk, fk in self.answers_cfg:
                if fk == f["slug"]:
                    self.answer_page(f, nk)

    def food_faq(self, f: dict) -> list[dict]:
        name = short_name(f["name"])
        ln = lower_name(f["name"])
        g = f["serving"]["g"]
        serv = f["serving"]["short"] if not f["serving"].get("fallback") else "100 g"
        faq = [{"q": f"How many calories are in {ln}?",
                "a": f"{name} has {fmt(f['kcal'], 0)} calories per {serv} ({g:g} g), or {fmt(f['n'].get('energy'), 0)} calories per 100 g, according to USDA FoodData Central."}]
        p = self.per(f["n"], "protein", g)
        if p is not None:
            faq.append({"q": f"How much protein is in {ln}?", "a": f"{fmt(p)} g of protein per {serv}, which is {pct(self.dv('protein', p))} of the 50 g Daily Value."})
        if f["highlights"]:
            h = f["highlights"][0]
            faq.append({"q": f"What is {ln} rich in?",
                        "a": f"Per serving, {ln} is richest in {h['name']} at {pct(h['dv'])} of the Daily Value" +
                             (", " + ", ".join(f"{r['name']} ({pct(r['dv'])})" for r in f["highlights"][1:4]) if len(f["highlights"]) > 1 else "") + "."})
        if f.get("nrf") is not None:
            faq.append({"q": f"Is {ln} healthy?",
                        "a": f"By nutrient density, {ln} scores {fmt(f['nrf'], 0)} on the NRF9.3 index (nine nutrients to encourage minus three to limit, per 100 kcal). "
                             f"Its nutrient profile is {f['dii_label']} compared with other whole foods. See the methodology page for how both scores work; this is data, not medical advice."})
        return faq

    def answer_page(self, f: dict, key: str):
        nd = self.N[key]
        name = short_name(f["name"])
        ln = lower_name(f["name"])
        nshort = re.sub(r"\s*\(.*?\)", "", nd["name"])
        nlow = nshort[0].lower() + nshort[1:]
        unit = nd["unit"]
        per100 = f["n"].get(key)
        if per100 is None:
            return
        rows = []
        for p in f["portions"]:
            amt = per100 * p["g"] / 100.0
            rows.append({"label": p["label"], "g": p["g"], "amount": amt, "dv": self.dv(key, amt)})
        g = f["serving"]["g"]
        amt = per100 * g / 100.0
        serv = f["serving"]["short"]
        dvtxt = f", which is {pct(self.dv(key, amt))} of the Daily Value" if nd.get("dv") else ""
        answer = f"{name} has {fmt(amt, nd.get('decimals', 1))} {unit} of {nlow} per {serv} ({g:g} g){dvtxt}. Per 100 g it contains {fmt(per100, nd.get('decimals', 1))} {unit}."
        rank = f["ranks"].get(key)
        rank_txt = ""
        if rank and rank.get("group"):
            rank_txt = f" Among {GROUP_SLUG_NAMES[f['group']].lower()} it ranks #{rank['group']} of {rank['group_n']} for {nlow} per serving"
            if rank.get("all"):
                rank_txt += f", and #{rank['all']} of {rank['all_n']} across all whole foods"
            rank_txt += "."
        variants = [{"label": v["label"], "per100": v["n"].get(key), "amount": (v["n"].get(key) or 0) * v["serving"]["g"] / 100 if v["n"].get(key) is not None else None,
                     "serving": v["serving"]["short"]} for v in f["variants"] if v["n"].get(key) is not None]
        top = self.rankings[key]["all"][:5] if key in self.rankings else []
        path = f"/food/{f['slug']}/{nd['slug']}/"
        title = f"{nshort} in {name}: How Much per Serving (%DV)"
        if len(title) > 60:
            title = f"{nshort} in {name} per Serving"
        faq = [{"q": f"How much {nlow} is in {ln}?", "a": answer},
               {"q": f"Is {ln} high in {nlow}?",
                "a": (f"Yes. At {pct(self.dv(key, amt))} of the Daily Value per serving, {ln} counts as {'an excellent' if self.dv(key, amt) >= 20 else 'a good'} source under FDA labeling rules (10% is 'good', 20% is 'high')."
                      if nd.get("dv") and self.dv(key, amt) >= 10 else
                      f"Not especially. One serving provides {pct(self.dv(key, amt))} of the Daily Value, below the 10% FDA threshold for a 'good source'." if nd.get("dv") else
                      f"There is no Daily Value for {nlow}; {ln} provides {fmt(amt, nd.get('decimals', 1))} {unit} per serving. See the ranking for how that compares.") + rank_txt}]
        if nd.get("dv"):
            faq.append({"q": f"How much {nlow} do I need a day?", "a": f"The FDA Daily Value is {fmt(nd['dv'], 2)} {unit}. One {serv} of {ln} covers {pct(self.dv(key, amt))} of it."})
        ld = [faq_ld(faq)]
        self.render("answer.html", path, title, answer + rank_txt,
                    crumbs=[("/", "Home"), ("/food/", "Foods"), (f["url"], name), (path, f"{nshort}")], jsonld=ld, priority=0.7,
                    f=f, nd=nd, key=key, rows=rows, answer=answer, rank_txt=rank_txt, variants=variants, top=top, nlow=nlow, nshort=nshort, unit=unit, faq=faq)
        self.search.append({"t": f"{nshort} in {ln}", "u": path, "d": "Nutrient in food", "k": f"{nlow} {f.get('aliases', '')}"})

    def compare_pages(self):
        self.render("compare_index.html", "/compare/", f"Food Nutrition Comparisons: {len(self.comps)} Pairs",
                    f"{len(self.comps)} side-by-side nutrition comparisons, from kale vs spinach to quinoa vs brown rice: calories, protein, "
                    f"fiber, vitamins and minerals per serving and per 100 g, with a data-driven verdict.",
                    crumbs=[("/", "Home"), ("/compare/", "Compare")], priority=0.9, comps=self.comps, foods=sorted(self.foods, key=lambda f: f["name"]))
        for c in self.comps:
            a, b = c["a"], c["b"]
            an, bn = short_name(a["name"]), short_name(b["name"])
            title = f"{c['title']}: Nutrition Compared Side by Side"
            if len(title) > 60:
                title = f"{c['title']}: Nutrition Comparison"
            related = [x for x in self.comps if x["id"] != c["id"] and ({x["a"]["slug"], x["b"]["slug"]} & {a["slug"], b["slug"]})][:8]
            faq = [{"q": f"Which is healthier, {an} or {bn}?",
                    "a": " ".join(c["verdict"]) + f" By nutrient density (NRF9.3 per 100 kcal) {an} scores {fmt(a['nrf'], 0)} and {bn} scores {fmt(b['nrf'], 0)}. Which is 'healthier' depends on what you need more of."},
                   {"q": f"Which has more protein, {an} or {bn}?",
                    "a": self.more_text(a, b, "protein")},
                   {"q": f"Which has fewer calories, {an} or {bn}?",
                    "a": self.more_text(a, b, "energy", fewer=True)}]
            ld = [faq_ld(faq), {"@context": "https://schema.org", "@type": "ItemList", "name": c["title"], "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": a["name"], "url": SITE_URL + a["url"]},
                {"@type": "ListItem", "position": 2, "name": b["name"], "url": SITE_URL + b["url"]}]}]
            desc = f"{c['title']}: {' '.join(c['verdict'][:2])} Full side-by-side nutrition per serving and per 100 g."
            self.render("compare.html", f"/compare/{c['id']}/", title, desc,
                        crumbs=[("/", "Home"), ("/compare/", "Compare"), (f"/compare/{c['id']}/", c["title"])], jsonld=ld, priority=0.8,
                        c=c, a=a, b=b, an=an, bn=bn, related=related, faq=faq)
            write(DOCS / "compare" / f"{b['slug']}-vs-{a['slug']}" / "index.html", redirect_stub(f"/compare/{c['id']}/", c["title"]))
            self.search.append({"t": c["title"], "u": f"/compare/{c['id']}/", "d": "Comparison", "k": f"{bn} vs {an}"})

    def more_text(self, a: dict, b: dict, key: str, fewer: bool = False) -> str:
        nd = self.N[key]
        an, bn = short_name(a["name"]), short_name(b["name"])
        va, vb = a["n"].get(key), b["n"].get(key)
        if va is None or vb is None:
            return "USDA does not report that value for both foods."
        unit = "kcal" if key == "energy" else nd["unit"]
        label = "calories" if key == "energy" else nd["name"].lower()
        if abs(va - vb) < 1e-9:
            return f"They are equal at {fmt(va)} {unit} per 100 g."
        win = (an if va < vb else bn) if fewer else (an if va > vb else bn)
        return f"{win}: {fmt(va, nd.get('decimals', 1))} {unit} per 100 g for {an} vs {fmt(vb, nd.get('decimals', 1))} {unit} for {bn}" + \
               (f" ({fmt(self.per(a['n'], key, a['serving']['g']), nd.get('decimals', 1))} vs {fmt(self.per(b['n'], key, b['serving']['g']), nd.get('decimals', 1))} {unit} per serving)." if True else ".")

    def healthiest_pages(self):
        cats = [{"slug": s, **h} for s, h in self.healthiest.items()]
        self.render("healthiest_index.html", "/healthiest/", f"Healthiest Foods by Category: {len(cats)} Ranked Lists",
                    "Healthiest bread, cereal, cheese, fast food, energy drinks, protein bars, milk, fruits, vegetables and nuts, each ranked "
                    "with a transparent nutrient-density score from USDA data.", crumbs=[("/", "Home"), ("/healthiest/", "Healthiest")],
                    priority=0.9, cats=cats)
        for slug, h in self.healthiest.items():
            rows = h["rows"]
            t1 = rows[0]
            noun = h["noun"]
            title = f"Healthiest {h['name']}: {len(rows)} {noun[0].upper() + noun[1:]} Ranked by Nutrition"
            if len(title) > 60:
                title = f"Healthiest {h['name']}: {len(rows)} Ranked by Nutrition"
            if len(title) > 60:
                title = f"Healthiest {h['name']} Ranked (USDA Data)"
            cols = [(k, self.N[k]) for k in h["columns"]]
            desc = (f"{len(rows)} {noun} ranked by a transparent nutrient-density score from USDA data. {t1.get('short', t1['name'])} ranks first, "
                    f"followed by {rows[1].get('short', rows[1]['name'])} and {rows[2].get('short', rows[2]['name'])}. Calories, protein, fiber and more per serving.")
            faq = [{"q": f"What is the healthiest {h['name'].lower()}?",
                    "a": f"By nutrient density per 100 calories (NRF9.3) {t1['name']} ranks first of {len(rows)} {noun} in the USDA database, "
                         f"with {fmt(t1['kcal'], 0)} calories per {t1['serving']}. {rows[1]['name']} and {rows[2]['name']} follow. The score rewards protein, fiber, vitamins and minerals and penalises saturated fat, sugar and sodium."
                    if h["score"] != "drink" else
                    f"Ranked by sugar and calories per 8 fl oz, {t1['name']} comes first with {fmt(t1['per'].get('sugars'), 0)} g sugar and {fmt(t1['kcal'], 0)} calories; caffeine is {fmt(t1['per'].get('caffeine'), 0)} mg per 8 fl oz."},
                   {"q": f"How are these {noun} ranked?",
                    "a": h["intro"] + " Every value comes from USDA FoodData Central; see the methodology page for the formula."},
                   {"q": f"Which {h['name'].lower()} should I avoid?",
                    "a": f"{rows[-1]['name']} ranks last of {len(rows)} on this measure" + (f", with {fmt(rows[-1]['kcal'], 0)} calories per {rows[-1]['serving']}." if rows[-1].get("kcal") else ".") +
                         " 'Last' here means lowest nutrient density per calorie, not that a food is harmful."}]
            ld = [faq_ld(faq), dataset_ld(f"Healthiest {h['name'].lower()} ranking", desc, f"{SITE_URL}/healthiest/{slug}/"),
                  {"@context": "https://schema.org", "@type": "ItemList", "name": f"Healthiest {h['name'].lower()}", "numberOfItems": len(rows),
                   "itemListElement": [{"@type": "ListItem", "position": r["rank"], "name": r["name"]} for r in rows[:20]]}]
            self.render("healthiest.html", f"/healthiest/{slug}/", title, desc,
                        crumbs=[("/", "Home"), ("/healthiest/", "Healthiest"), (f"/healthiest/{slug}/", f"Healthiest {h['name'].lower()}")],
                        jsonld=ld, priority=0.9, h=h, slug=slug, rows=rows, cols=cols, faq=faq, others=[c for c in cats if c["slug"] != slug])
            self.search.append({"t": f"Healthiest {h['name'].lower()}", "u": f"/healthiest/{slug}/", "d": f"{len(rows)} {noun} ranked"})

    def category_pages(self):
        groups = [self.cats[g] for g in self.meta["rank_groups"]]
        self.render("category_index.html", "/category/", "Food Groups: Nutrient Profiles and Rankings",
                    "Browse foods by group: fruits, vegetables, legumes, nuts and seeds, grains, fish, meat and dairy. Median nutrients per serving, "
                    "the richest food for each nutrient and links to every ranking.", crumbs=[("/", "Home"), ("/category/", "Food groups")],
                    priority=0.7, groups=groups)
        for c in groups:
            g = c["slug"]
            foods = [self.F[s] for s in c["pages"] if s in self.F]
            foods.sort(key=lambda f: f["name"])
            stats = [(k, self.N[k], c["stats"][k]) for k in self.rank_keys if k in c["stats"] and c["stats"][k]["top"]]
            name = GROUP_SLUG_NAMES[g]
            title = f"{name}: Nutrition Rankings and Richest Sources"
            if len(title) > 60:
                title = f"{name}: Nutrition Rankings"
            top_lines = ", ".join(f"{self.N[k]['name'].lower() if not self.N[k]['name'].startswith('Vit') else self.N[k]['name']} ({st['top']['name']})" for k, _, st in stats[:4])
            desc = f"{c['count']} {name.lower()} in the ranking pool. Richest sources of {top_lines}. Median nutrients per serving and {len(foods)} full nutrition profiles."
            self.render("category.html", f"/category/{g}/", title, desc, crumbs=[("/", "Home"), ("/category/", "Food groups"), (f"/category/{g}/", name)],
                        priority=0.7, c=c, g=g, foods=foods, stats=stats, name=name,
                        subpages=[k for k in self.ndefs["subpage_nutrients"] if g in self.rankings[k]["groups"]])
            self.search.append({"t": name, "u": f"/category/{g}/", "d": "Food group"})

    def guide_pages(self):
        rank_groups = set(self.meta["rank_groups"])
        whole = [f for f in self.pool if f["group"] in rank_groups]

        def dedupe(rows, n):
            seen, out = set(), []
            for f in rows:
                if f["family"] in seen:
                    continue
                seen.add(f["family"])
                out.append(f)
                if len(out) >= n:
                    break
            return out

        def serv_rows(fs, keys):
            out = []
            for f in fs:
                g = f["serving"]["g"]
                r = {"name": f["name"], "page": f.get("page"), "serving": f["serving"]["short"], "group": GROUP_SLUG_NAMES[f["group"]],
                     "kcal": self.per(f["n"], "energy", g), "nrf": f.get("nrf"), "dii": f.get("dii"), "dii_label": f.get("dii_label"), "vals": {}}
                for k in keys:
                    v = self.per(f["n"], k, g)
                    r["vals"][k] = (v, self.dv(k, v))
                out.append(r)
            return out

        # 1. anti-inflammatory
        ai = sorted([f for f in whole if f.get("dii") is not None and self.per(f["n"], "energy", f["serving"]["g"]) >= 10], key=lambda f: f["dii"])
        ai_top = dedupe(ai, 50)
        ai_bottom = dedupe(list(reversed(ai)), 12)
        # 2. electrolytes
        el_keys = ["potassium", "magnesium", "calcium", "sodium"]
        for f in whole:
            g = f["serving"]["g"]
            f["_el"] = sum((self.dv(k, self.per(f["n"], k, g)) or 0) for k in ("potassium", "magnesium", "calcium")) + min(10, self.dv("sodium", self.per(f["n"], "sodium", g)) or 0)
        el = dedupe(sorted([f for f in whole if "potassium" in f["n"] and "magnesium" in f["n"]], key=lambda f: -f["_el"]), 40)
        # 3. vegetarian iron
        veg_iron = [r for r in self.rankings["iron"]["all"] if r["group"] not in ("meat", "fish-seafood")]
        veg_iron_pool = dedupe(sorted([f for f in whole if f["group"] not in ("meat", "fish-seafood") and "iron" in f["n"]],
                                      key=lambda f: -self.per(f["n"], "iron", f["serving"]["g"])), 40)
        # 4. nutrient dense
        nd_top = dedupe(sorted([f for f in whole if f.get("nrf") is not None and self.per(f["n"], "energy", f["serving"]["g"]) >= 10], key=lambda f: -f["nrf"]), 50)
        guides = [
            {"slug": "anti-inflammatory-foods", "title": "Anti-Inflammatory Foods: 50 Ranked by Nutrient Profile",
             "h1": "Anti-inflammatory foods, ranked by nutrient profile",
             "summary": f"50 whole foods whose nutrient profile scores most anti-inflammatory on a Dietary Inflammatory Index adaptation: "
                        f"{short_name(ai_top[0]['name'])}, {short_name(ai_top[1]['name'])}, {short_name(ai_top[2]['name'])} and more, with the USDA data behind each.",
             "rows": serv_rows(ai_top, ["fiber", "magnesium", "vit_c", "vit_e", "omega3"]), "cols": ["fiber", "magnesium", "vit_c", "vit_e", "omega3"],
             "bottom": serv_rows(ai_bottom, ["sat_fat", "fiber", "magnesium"]), "kind": "dii"},
            {"slug": "electrolyte-foods", "title": "Foods High in Electrolytes: 40 Ranked (Potassium, Mg, Ca)",
             "h1": "Foods high in electrolytes",
             "summary": f"40 whole foods ranked by combined potassium, magnesium and calcium per serving (%DV), with sodium shown. "
                        f"{short_name(el[0]['name'])}, {short_name(el[1]['name'])} and {short_name(el[2]['name'])} lead.",
             "rows": serv_rows(el, el_keys), "cols": el_keys, "kind": "el"},
            {"slug": "iron-rich-foods-for-vegetarians", "title": "Iron-Rich Foods for Vegetarians: 40 Plant & Dairy Sources",
             "h1": "Iron-rich foods for vegetarians and vegans",
             "summary": f"40 plant-based and dairy sources of iron ranked per serving: {short_name(veg_iron_pool[0]['name'])} leads with "
                        f"{fmt(self.per(veg_iron_pool[0]['n'], 'iron', veg_iron_pool[0]['serving']['g']))} mg. Vitamin C per serving is shown because it boosts non-heme iron absorption.",
             "rows": serv_rows(veg_iron_pool, ["iron", "vit_c", "protein", "fiber"]), "cols": ["iron", "vit_c", "protein", "fiber"], "kind": "iron"},
            {"slug": "most-nutrient-dense-foods", "title": "The 50 Most Nutrient-Dense Foods (NRF9.3 per 100 kcal)",
             "h1": "The most nutrient-dense foods",
             "summary": f"50 whole foods with the highest nutrient density per calorie on the NRF9.3 index: {short_name(nd_top[0]['name'])}, "
                        f"{short_name(nd_top[1]['name'])}, {short_name(nd_top[2]['name'])} and more, with calories and %DV per serving.",
             "rows": serv_rows(nd_top, ["protein", "fiber", "vit_a", "vit_c", "potassium"]), "cols": ["protein", "fiber", "vit_a", "vit_c", "potassium"], "kind": "nrf"},
        ]
        self.guides = [{"slug": g["slug"], "title": g["h1"][0].upper() + g["h1"][1:], "summary": g["summary"]} for g in guides]
        for g in guides:
            assert len(g["title"]) <= 60, g["title"]
            path = f"/guide/{g['slug']}/"
            ld = [{"@context": "https://schema.org", "@type": "Article", "headline": g["title"], "description": g["summary"], "image": OG_IMAGE,
                   "datePublished": PUBLISHED, "dateModified": DATA_UPDATED, "author": {"@type": "Organization", "name": SITE_NAME},
                   "publisher": {"@type": "Organization", "name": SITE_NAME, "logo": SITE_URL + "/favicon-512.png"}, "mainEntityOfPage": SITE_URL + path},
                  {"@context": "https://schema.org", "@type": "ItemList", "name": g["h1"], "itemListElement": [
                      {"@type": "ListItem", "position": i + 1, "name": r["name"]} for i, r in enumerate(g["rows"][:25])]}]
            self.render("guide.html", path, g["title"], g["summary"], crumbs=[("/", "Home"), ("/guide/", "Guides"), (path, g["h1"][0].upper() + g["h1"][1:])],
                        jsonld=ld, priority=0.8, g=g, cols=[(k, self.N[k]) for k in g["cols"]], guides=self.guides)
            self.search.append({"t": g["h1"][0].upper() + g["h1"][1:], "u": path, "d": "Guide"})
        self.render("guide_index.html", "/guide/", "Nutrition Guides Built From USDA Data",
                    "Data-driven food guides: anti-inflammatory foods, electrolyte-rich foods, iron for vegetarians and the most nutrient-dense foods, each ranked from USDA values with the method shown.",
                    crumbs=[("/", "Home"), ("/guide/", "Guides")], priority=0.7, guides=self.guides)

    def static_pages(self):
        pages = [
            ("page_about.html", "/about/", "About NutrientChart", "What NutrientChart is, where the data comes from (USDA FoodData Central), who it is for and how to report an error."),
            ("page_methodology.html", "/about/methodology/", "Methodology: Servings, %DV and Scores", "How NutrientChart ranks foods: serving sizes, the whole-food filter, FDA Daily Values, the NRF9.3 nutrient-density score and the inflammatory profile score."),
            ("page_data_sources.html", "/about/data-sources/", "Data Sources and Licensing", "The datasets behind NutrientChart: USDA SR Legacy and Foundation Foods (CC0), FDA Daily Values and the research behind the scores."),
            ("page_privacy.html", "/privacy/", "Privacy Policy", "NutrientChart privacy policy: no accounts or forms, cookies used by Google AdSense and analytics, consent for EU visitors."),
            ("page_terms.html", "/terms/", "Terms of Use", "NutrientChart terms of use: nutrition data for general information only, not medical advice, no warranty."),
        ]
        for tpl, path, title, desc in pages:
            crumbs = [("/", "Home")] + ([("/about/", "About")] if path.startswith("/about/") and path != "/about/" else []) + [(path, title.split(":")[0])]
            self.render(tpl, path, f"{title} | {SITE_NAME}" if len(title) + len(SITE_NAME) + 3 <= 60 and SITE_NAME not in title else title,
                        desc, crumbs=crumbs, priority=0.3, heading=title, pool_n=len(self.pool), food_n=len(self.foods),
                        rank_n=len(self.rank_keys), ndefs=self.ndefs)
        self.render("404.html", "/404.html", f"Page Not Found | {SITE_NAME}", "Page not found.", is_404=True, crumbs=[("/", "Home"), ("/404.html", "Page not found")])

    def finish(self):
        sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        sm += [f"  <url><loc>{SITE_URL}{u}</loc><lastmod>{DATA_UPDATED}</lastmod><priority>{p:.1f}</priority></url>" for u, p in sorted(self.urls)]
        sm.append("</urlset>")
        write(DOCS / "sitemap.xml", "\n".join(sm) + "\n")
        write(DOCS / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")
        write(DOCS / "ads.txt", f"google.com, {ADSENSE_PUB.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
        write(DOCS / "search-index.json", json.dumps(self.search, separators=(",", ":"), ensure_ascii=False))
        write(DOCS / "CNAME", DOMAIN + "\n")
        write(DOCS / ".nojekyll", "")
        shutil.copytree(ROOT / "static", DOCS / "static")
        fav = ROOT / "favicon"
        if fav.exists():
            for f in fav.iterdir():
                shutil.copy2(f, DOCS / f.name)


def main() -> int:
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir()
    site = Site()
    site.home()
    site.ranking_pages()
    site.food_pages()
    site.compare_pages()
    site.healthiest_pages()
    site.category_pages()
    site.guide_pages()
    site.static_pages()
    site.finish()
    print(f"built {len(site.urls)} pages into docs/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
