# nutrientchart.com

Nutrient-first food database: "foods high in X" rankings per serving, food nutrition profiles, comparisons,
"healthiest [category]" lists and data-driven guides. Python + Jinja2 generate a static site into `docs/`
(GitHub Pages, Cloudflare in front). Same pattern as steelchart.org / pipedata.org.

## Git identity: always pseudonymous

- Commit as `729r2pzfqs-ux <729r2pzfqs-ux@users.noreply.github.com>` (set in the repo-local git config).
- Contact address on the site is info@nutrientchart.com. Never put a personal name or email in files or page source.

## Layout

```
tools/fetch_usda.py     downloads the pinned USDA zips into data/source/ (git-ignored)
tools/build_data.py     parses the CSVs -> data/*.json (pool, rankings, foods, healthiest, categories, meta)
data/curated/           hand-maintained inputs: foods.json (page list + regex match + variants + serving hint),
                        nutrients.json (ids, DVs, DII weights, rank order), comparisons.json, answers.json,
                        healthiest.json (category member regexes, serving rule, score, columns)
data/*.json             build inputs (committed)
build.py                renders docs/; all generated prose + JSON-LD live here
svg.py                  inline SVG: ranking bars, compare bars, calorie donut
templates/              Jinja2 (base, macros, one per page type, legal pages, 404)
static/                 style.css, site.js (search, sort, filter, serving tabs, theme), og-image.png
favicon/                scripts/make_favicons.py output; build copies to the site root
```

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python3 tools/fetch_usda.py            # once; re-run when adopting a new Foundation Foods release
python3 tools/build_data.py            # when data/curated or data/source changes
.venv/bin/python build.py
python3 -m http.server 8767 -d docs    # local preview
```

## Data rules

- Every number on a page comes from data/*.json; every sentence with a number is generated in build.py.
- USDA values are per 100 g. Per serving = amount * gram_weight / 100. A missing nutrient is "not analysed",
  never zero: show "—" and leave the food out of that nutrient's ranking.
- Rankings are per common serving (rules in build_data.rules_for). Per-100 g lists are dominated by powders
  and dried items; that is the whole point of the site.
- The whole-food pool excludes spices, baby foods, powders/flours, dried produce (except dates/figs/prunes/
  raisins), juices, "with salt" items, fortified cereals, processed/cured meats, organ meats except liver,
  fat trimmings and uncommon foods (EXCLUDE_ALL / EXOTIC regexes). One entry per food family, max 6 per head.
- Foundation Foods values > 0 override SR Legacy values for the same NDB number; a Foundation amount of 0
  is ambiguous (below LOQ) and is not used.
- Scores: NRF9.3 per 100 kcal (total sugars proxy for added sugars) and the DII-weighted inflammatory
  profile score (centered; labels are pool percentiles). Both are documented on /about/methodology/ and the
  description there must match the code.
- Titles must be <= 60 chars (render() asserts). Descriptions are trimmed to 158 chars.
- Comparison URLs are alphabetical by slug; the reverse URL is a noindex meta-refresh stub with a canonical.

## Site settings (top of build.py)

- `ADSENSE_PUB` is set; `GA_ID` is empty (GA tags omitted) until the GA4 property exists; `AD_SLOTS` empty = auto ads.
- `DATA_UPDATED` drives dateModified, sitemap lastmod and "Updated" lines; bump it when data or page content changes.
