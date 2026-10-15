#!/usr/bin/env python3
"""Build data/*.json from the USDA FoodData Central CSV archives in data/source/.

    python3 tools/build_data.py

Inputs : data/source/*.zip (SR Legacy 2018-04, Foundation Foods 2026-04-30; see tools/fetch_usda.py)
         data/curated/*.json (food pages, nutrient definitions, comparison pairs, "healthiest" categories)
Outputs: data/nutrients.json  nutrient definitions with FDA Daily Values
         data/foods.json      curated food pages: per-100 g values, servings, variants, scores, ranks, sources
         data/pool.json       the ranking pool of whole foods (deduplicated, per-serving values)
         data/rankings.json   "foods high in X" lists: all foods and per food group, plus "low in" lists
         data/healthiest.json "healthiest [category]" lists with scores
         data/categories.json food-group stats for the hub pages
         data/meta.json       release dates and counts

Every nutrient amount in the CSVs is per 100 g of edible portion. Per-serving = amount * gram_weight / 100.
A nutrient row that is absent means "not analysed", never zero; such foods are left out of that ranking.
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "source"
CUR = ROOT / "data" / "curated"
OUT = ROOT / "data"
SR_ZIP = SRC / "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
FND_ZIP = SRC / "FoodData_Central_foundation_food_csv_2026-04-30.zip"
SR_RELEASE, FND_RELEASE = "April 2018", "April 2026"

GROUPS = {  # USDA food_category -> site food group
    "Fruits and Fruit Juices": "fruits", "Vegetables and Vegetable Products": "vegetables",
    "Legumes and Legume Products": "legumes", "Nut and Seed Products": "nuts-seeds",
    "Cereal Grains and Pasta": "grains", "Breakfast Cereals": "grains",
    "Finfish and Shellfish Products": "fish-seafood", "Beef Products": "meat", "Pork Products": "meat",
    "Poultry Products": "meat", "Lamb, Veal, and Game Products": "meat", "Dairy and Egg Products": "dairy-eggs",
    "Fats and Oils": "fats-oils",
}
GROUP_NAMES = {"fruits": "Fruits", "vegetables": "Vegetables", "legumes": "Legumes", "nuts-seeds": "Nuts & seeds",
               "grains": "Grains", "fish-seafood": "Fish & seafood", "meat": "Meat & poultry",
               "dairy-eggs": "Dairy & eggs", "fats-oils": "Fats & oils", "other": "Other foods"}
RANK_GROUPS = ["fruits", "vegetables", "legumes", "nuts-seeds", "grains", "fish-seafood", "meat", "dairy-eggs"]
# whole-food filter for the ranking pool
EXCLUDE_ALL = re.compile(r"dehydrated|powder|freeze-dried|instant|concentrate|, dry$|, dry,|dry mix|mix, dry|"
                         r"baby|infant|juice|syrup|, with salt|, with added salt|salted|, salt added|"
                         r"mechanically separated|imitation|substitute|restaurant|fast food|"
                         r"evaporated|condensed|(?<!un)sweetened|candied|glazed|pickled|brined|fermented|"
                         r"industrial|school|USDA Commodity|ready-to-eat|fortified|enriched|cooked, fried|battered|breaded|"
                         r"human|whale|seal|walrus|caribou|bear|moose|muktuk|oopah|alaska native|navajo|hopi|apache|"
                         r"\bflour|\bbran\b|\bgerm\b|extender|\bpaste\b|puree|sauce|catsup|ketchup|crude|textured|isolate|meatless|"
                         r"anhydrous|butter oil|rendered|\blard\b|tallow|drippings|liquid from|composite|carob|pimento|"
                         r"pokeberry|drumstick|lemon grass|lemongrass|curd cheese|natto|miso|\bemu\b|ostrich|"
                         r"\b(spleen|kidney|kidneys|heart|brain|brains|lungs|pancreas|thymus|tongue|tripe|ears|feet|tail|snout|jowl|"
                         r"chitterlings|stomach|intestine|intestines|giblets|gizzard|sweetbread|sweetbreads|roe|caviar|blood)\b|skin only|"
                         r"nonfat or fat free|fat free|reduced fat|low fat|lowfat|, light\b|chocolate|cocoa|carbonated|"
                         r"protein fortified|added nonfat milk solids|calcium fortified|buffalo|camel|reindeer",
                         re.I)
GRAIN_OK = re.compile(r"cooked|not fortified|popcorn", re.I)
# uncommon foods, processed meats and fat trimmings kept out of the "whole foods" ranking pool
EXOTIC = re.compile(r"^Soybeans, green, raw|chili|baked|barbecue|franks|refried|with pork|succotash|cottonseed|sisymbrium|breadnut|"
                    r"butternuts|acorn|ginkgo|hickory|beechnuts|\bpili\b|coconut (milk|cream|water)|cured|bacon|\bham\b|sausage|"
                    r"frankfurter|bologna|salami|pepperoni|jerky|corned|separable fat|fat only|subcutaneous|pate|foie|"
                    r"beaver|muskrat|raccoon|opossum|squirrel|armadillo|\bboar\b|antelope|horse|filled|producer|SILK|"
                    r"with peel|rhubarb|\bnance\b|chrysanthemum|\bdock\b|lambsquarters|sweet potato leaves|fireweed|epazote|"
                    r"balsam|\bjute\b|taro leaves|pumpkin leaves|borage|vinespinach|winged bean|cowpeas, leafy|arrowhead|"
                    r"yautia|yambean|mountain yam|hyacinth|mothbeans|yardlong|catjang|lupins|cherimoya|sapote|breadfruit|"
                    r"durian|jackfruit|tamarind|soursop|acerola|longans|mamey|abiyuch|carissa|feijoa|jujube|loquat|"
                    r"oheloberries|rose-apples|roselle|sapodilla|whelk|conch|cuttlefish|periwinkle|abalone|snail|frog|turtle|"
                    r"School Lunch|unspecified|mixed species, smoked|kippered|amaranth|mushrooms, morel|mushrooms, maitake|"
                    r"mushrooms, enoki|mushrooms, straw|lotus|wasabi|burdock|cassava|epazote|hearts of palm|salsify|"
                    r"nopales|cardoon|celtuce|chayote|chicory|jew's ear|kanpyo|kohlrabi|poi|taro|tree fern|waxgourd|"
                    r"yam, raw|arugula, raw$|grape leaves|sesbania|shallots|wax beans|lima beans, immature seeds \(raw|"
                    r"cowpeas \(blackeyes\), immature|jerusalem|peas, edible-podded \(frozen|collards, frozen|turnip greens, frozen|"
                    r"turnip greens and turnips|spinach, frozen|kale, frozen|broccoli, frozen|mustard greens, frozen|beet greens, raw|"
                    r"currants, european|elderberries|gooseberries|mulberries|quinces|boysenberries|loganberries|"
                    r"kiwifruit, ZESPRI|guavas, strawberry|crabapples|java-plum|groundcherries|pitanga|rowal|prunes, canned|"
                    r"pork, fresh, variety|lamb, variety|lamb, new zealand, imported, liver|veal, variety|beef, new zealand, imported, variety|"
                    r"turkey, all classes \(liver|chicken, liver|game meat, (deer|elk|bison|moose|caribou|antelope|goat|rabbit|buffalo|boar)\b.*\b(liver|tongue|heart|kidney)\b|"
                    r"veal, (leg|shoulder|cubed|breast|loin|rib|sirloin|external)|yogurt, plain \(skim|milk, sheep|milk, goat|romano|"
                    r"cheese, parmesan \(shredded|salmon, sockeye \(canned|fish, sturgeon|fish, herring|fish, anchovy|fish, roe|fish, shad|fish, pout|"
                    r"fish, whitefish|fish, cisco|fish, drum|fish, burbot|fish, carp|fish, croaker|fish, cusk|fish, dolphinfish|fish, eel|"
                    r"fish, lingcod|fish, milkfish|fish, monkfish|fish, mullet|fish, ocean perch|fish, pike|fish, pollock, atlantic|"
                    r"fish, pompano|fish, rockfish|fish, roughy|fish, sablefish|fish, scup|fish, sheepshead|fish, smelt|fish, snapper|"
                    r"fish, spot|fish, sucker|fish, sunfish|fish, tilefish|fish, turbot|fish, wolffish|fish, yellowtail|fish, bluefish|fish, butterfish|"
                    r"mollusks, octopus|mollusks, squid|mollusks, abalone|mollusks, cuttlefish|mollusks, whelk|mollusks, snail|crustaceans, spiny|crustaceans, crayfish|"
                    r"water convolvulus|\bmeal\b|melon balls|au gratin|scalloped|home-prepared|hash brown|cheese, [a-z ]+, nonfat|tofu yogurt|enhanced|"
                    r"plantains, green \(fried|pummelo|prickly pears|watermelon seed|safflower|mustard spinach|stir-fried|kimchi|sauerkraut|pickle|relish|olives, pickled",
                    re.I)
CANNED_OK = re.compile(r"^Tomato", re.I)
EXCLUDE_DRIED = re.compile(r"dried|dehydrated|chips", re.I)          # fruits & vegetables only
EXCLUDE_RAW = re.compile(r"\braw\b|uncooked|unprepared|unheated", re.I)  # meat, fish, legumes, grains: rank cooked only
PREP = re.compile(r"^(raw|cooked|frozen|canned|boiled|fresh|dried|roasted|baked|fried|steamed|microwaved|unprepared|"
                  r"mature|all commercial|with|without|chopped|sliced|whole|fluid|plain|regular|prepared|ready|"
                  r"domestic|retail|broilers|composite|separable|lean|ground|variety|organic)", re.I)
STRIP = re.compile(r"\s*\((Includes foods for USDA's Food Distribution Program|includes [^)]*)\)|, year round average", re.I)


def read_zip_csv(zp: Path, name: str) -> list[dict]:
    with zipfile.ZipFile(zp) as z:
        member = next(n for n in z.namelist() if n.endswith("/" + name) or n == name)
        with z.open(member) as f:
            return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", newline="")))


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def pretty(desc: str) -> str:
    """'Spinach, cooked, boiled, drained, without salt' -> 'Spinach, cooked (boiled, drained, without salt)'."""
    d = STRIP.sub("", desc).strip().rstrip(",")
    parts = [p.strip() for p in d.split(",") if p.strip()]
    if len(parts) <= 2:
        return ", ".join(parts)
    return f"{parts[0]}, {parts[1]} ({', '.join(parts[2:])})"


def short_desc(desc: str) -> str:
    """Prose-friendly name: 'Beet greens, cooked' / 'Beans, adzuki' / 'Avocados' from the USDA description."""
    parts = [p.strip() for p in STRIP.sub("", desc).split(",") if p.strip()]
    if len(parts) == 1:
        return parts[0]
    if PREP.match(parts[1]):
        return f"{parts[0]}, {parts[1].lower()}" if parts[1].lower() in ("cooked", "raw", "canned", "frozen", "dried") else parts[0]
    return f"{parts[0]}, {parts[1]}"


def family_key(desc: str) -> str:
    parts = [p.strip().lower() for p in STRIP.sub("", desc).split(",") if p.strip()]
    key = parts[0]
    if parts[0] in ("chicken", "turkey") and len(parts) > 2:
        return f"{key}|{parts[2]}"
    if parts[0] == "beverages" and len(parts) > 2:
        return f"{parts[1]}|{parts[2]}"
    if len(parts) > 1 and not PREP.match(parts[1]):
        key += "|" + parts[1]
    return key


# ------------------------------------------------------------------ serving selection
SERVE_RULES = {  # label -> (regex on "amount modifier", preferred amount or None)
    "medium": (r"\bmedium\b", None), "large": (r"\blarge\b", None), "small": (r"\bsmall\b", None),
    "cup": (r"^1 cup\b", None), "halfcup": (r"^0\.5 cup\b", None), "oz": (r"^1 oz\b", None),
    "3oz": (r"^3 oz\b", None), "tbsp": (r"^1 (tbsp|tablespoon)\b", None), "tbsp2": (r"^2 tbsp\b", None),
    "tbsp3": (r"^3 tbsp\b", None), "slice": (r"^1 slice\b", None), "piece": (r"^1 (piece|date|prune|fig)\b", None),
    "clove": (r"^1 clove\b", None), "container": (r"^1 container\b", None), "nlea": (r"NLEA", None),
    "bar": (r"\bbar\b", None), "item": (r"^1 (item|sandwich|serving|burrito|taco|piece|each|order|salad|biscuit|"
                                       r"wrap|sub|burger|hot dog|slice|cup|bowl|entree|plate|package|side|roll|"
                                       r"quesadilla|chalupa|gordita|nachos|pizza|breakfast|meal)\b", None),
    "fl8": (r"^8 fl oz\b", None), "spear": (r"^1 (spear|stalk|ear|artichoke|sprout|floweret)\b", None),
    "fruit": (r"^1 (fruit|banana|apple|orange|pear|peach|plum|kiwi|melon|pepper|potato|tomato|carrot|onion|cucumber|"
              r"avocado|mango|sweetpotato|ear|head|bulb|leaf|wedge|pomegranate|grapefruit|lemon|lime)\b", None),
    "fillet": (r"^(1 fillet|0\.5 fillet|1 patty|1 chop|0\.5 breast|6 medium)\b", None),
    "egg": (r"^1 (large|extra large|jumbo|medium)\b", None),
    "tsp": (r"^1 (tsp|teaspoon)\b", None),
    "half": (r"^0\.5 (medium|large|fruit|grapefruit|avocado|melon)\b", None),
    "floz": (r"^1 fl oz\b", None),
}
GROUP_SERVE = {
    "fruits": ["medium", "fruit", "cup", "halfcup", "large", "small", "piece", "nlea"],
    "vegetables": ["cup", "medium", "fruit", "spear", "large", "halfcup", "nlea", "piece"],
    "legumes": ["cup", "halfcup", "tbsp2", "oz", "tbsp"],
    "nuts-seeds": ["oz", "tbsp", "cup", "tbsp3"],
    "grains": ["cup", "slice", "halfcup", "oz", "nlea", "piece"],
    "fish-seafood": ["3oz", "fillet", "oz", "cup"],
    "meat": ["3oz", "fillet", "oz", "cup", "slice"],
    "dairy-eggs": ["cup", "oz", "egg", "container", "tbsp", "slice", "halfcup"],
    "fats-oils": ["tbsp", "tsp"],
    "other": ["cup", "oz", "tbsp", "medium", "slice", "fl8", "piece"],
}


def portion_label(p: dict) -> str:
    amt = num(p["amount"]) or 0
    a = f"{amt:g}"
    mod = (p.get("modifier") or p.get("portion_description") or "").strip()
    return f"{a} {mod}".strip()


SYNTH = {"synth_oz": ("1 oz", 28.35), "synth_3oz": ("3 oz", 85.0), "synth_tbsp": ("1 tbsp", 13.6),
         "synth_fl8": ("8 fl oz", 240.0), "synth_2tbsp": ("2 tbsp", 30.0), "synth_halfcup": ("0.5 cup", None)}


def pick_serving(portions: list[dict], rules: list[str]) -> dict | None:
    """First portion matching the first rule that matches anything; synth_* rules make a standard portion."""
    ok = [p for p in portions if 3 <= (num(p["gram_weight"]) or 0) <= 450]
    ok.sort(key=lambda x: int(x["seq_num"] or 0))
    for r in rules:
        if r in SYNTH:
            label, g = SYNTH[r]
            if r == "synth_2tbsp":
                one = next((p for p in ok if re.match(r"^1 (tbsp|tablespoon)\b", portion_label(p), re.I)), None)
                g = 2 * num(one["gram_weight"]) if one else 30.0
            if r == "synth_halfcup":
                cup = next((p for p in ok if re.match(r"^1 cup\b", portion_label(p), re.I)), None)
                if not cup:
                    continue
                g = num(cup["gram_weight"]) / 2
            return {"amount": "1", "modifier": label, "gram_weight": f"{g:g}", "seq_num": "0", "synth": True}
        rx = re.compile(SERVE_RULES[r][0], re.I)
        for p in ok:
            if rx.search(portion_label(p)):
                return p
    return None


def rules_for(group: str, desc: str, first: str | None = None) -> list[str]:
    """Serving preference for a food: curated hint first, then description-based, then the group default."""
    d = desc.lower()
    rules = [first] if first else []
    if group == "fruits":
        if d.startswith("dates"):
            rules += ["piece"]
        elif re.search(r"dried|raisins|prunes", d):
            rules += ["synth_oz"]
        rules += ["medium", "fruit", "half", "cup", "halfcup", "large", "small", "piece", "nlea"]
    elif group == "vegetables":
        rules += ["cup", "medium", "halfcup", "spear", "fruit", "large", "nlea", "piece"]
    elif group == "legumes":
        if re.search(r"butter|hummus|tahini|spread", d):
            rules += ["tbsp2", "synth_2tbsp"]
        elif re.search(r"roasted|^peanuts|^nuts|^seeds", d):
            rules += ["oz", "synth_oz"]
        rules += ["cup", "halfcup", "oz", "tbsp"]
    elif group == "nuts-seeds":
        if re.search(r"butter|tahini", d):
            rules += ["tbsp2", "synth_2tbsp"]
        rules += ["oz", "synth_oz"]
    elif group == "grains":
        rules += ["cup", "slice", "halfcup", "oz", "nlea", "piece"]
    elif group in ("meat", "fish-seafood"):
        rules += ["3oz", "synth_3oz"]
    elif group == "dairy-eggs":
        if d.startswith("cheese"):
            rules += ["oz", "synth_oz"]
        elif d.startswith("egg"):
            rules += ["egg", "large"]
        elif d.startswith(("butter", "cream")):
            rules += ["tbsp", "synth_tbsp"]
        rules += ["cup", "container", "halfcup", "oz", "tbsp"]
    elif group == "fats-oils":
        rules += ["tbsp", "synth_tbsp"]
    else:
        rules += ["cup", "fl8", "oz", "tbsp", "medium", "slice", "piece"]
    return rules


def serving_dict(p: dict | None) -> dict:
    if p is None:
        return {"label": "100 g", "short": "100 g", "g": 100.0, "fallback": True}
    g = num(p["gram_weight"])
    if p.get("synth"):
        return {"label": f"{p['modifier']} ({g:g} g)", "short": p["modifier"], "g": g, "fallback": False}
    lab = portion_label(p)
    lab = re.sub(r"\(1 NLEA serving.*?\)", "", lab).replace("  ", " ").strip()
    lab = re.sub(r"^1 ", "1 ", lab)
    return {"label": f"{lab} ({g:g} g)", "short": lab, "g": g, "fallback": False}


# ------------------------------------------------------------------ main
def main() -> int:
    ndefs = json.loads((CUR / "nutrients.json").read_text())
    NUTS = ndefs["nutrients"]
    by_key = {n["key"]: n for n in NUTS}

    print("reading SR Legacy ...")
    sr_food = read_zip_csv(SR_ZIP, "food.csv")
    sr_cat = {r["id"]: r["description"] for r in read_zip_csv(SR_ZIP, "food_category.csv")}
    sr_nut = read_zip_csv(SR_ZIP, "food_nutrient.csv")
    sr_por = read_zip_csv(SR_ZIP, "food_portion.csv")
    sr_ndb = {r["fdc_id"]: r["NDB_number"] for r in read_zip_csv(SR_ZIP, "sr_legacy_food.csv")}
    nut_names = {r["id"]: r for r in read_zip_csv(SR_ZIP, "nutrient.csv")}
    print("reading Foundation Foods ...")
    fnd_food = [r for r in read_zip_csv(FND_ZIP, "food.csv") if r["data_type"] == "foundation_food"]
    fnd_ndb = {r["fdc_id"]: r["NDB_number"] for r in read_zip_csv(FND_ZIP, "foundation_food.csv")}
    fnd_nut = read_zip_csv(FND_ZIP, "food_nutrient.csv")

    # nutrient id -> key
    id2key: dict[str, str] = {}
    for n in NUTS:
        for i in n["ids"]:
            id2key.setdefault(str(i), n["key"])
    o3 = ndefs["omega3_ids"]
    o3_ids = {str(i): k for k, ids in o3.items() for i in ids}
    for i in o3_ids:
        assert i in nut_names, i
    for n in NUTS:
        for i in n["ids"]:
            assert str(i) in nut_names, f"nutrient id {i} ({n['key']}) not in nutrient.csv"

    # per food: nutrient amounts per 100 g (first id in the list wins)
    raw: dict[str, dict] = defaultdict(dict)          # fdc_id -> {nutrient_id: amount}
    for r in sr_nut:
        a = num(r["amount"])
        if a is not None:
            raw[r["fdc_id"]][r["nutrient_id"]] = a

    def profile(amounts: dict[str, float]) -> dict[str, float]:
        out = {}
        for n in NUTS:
            if n.get("computed"):
                continue
            for i in n["ids"]:
                if str(i) in amounts:
                    out[n["key"]] = amounts[str(i)]
                    break
        # omega-3 = ALA (1404, else 18:3 total) + EPA + DHA; only when at least EPA/DHA or ALA known
        ala = next((amounts[str(i)] for i in o3["ala"] if str(i) in amounts), None)
        epa = next((amounts[str(i)] for i in o3["epa"] if str(i) in amounts), None)
        dha = next((amounts[str(i)] for i in o3["dha"] if str(i) in amounts), None)
        if ala is not None or epa is not None or dha is not None:
            out["omega3"] = round((ala or 0) + (epa or 0) + (dha or 0), 3)
        return out

    # Foundation overlay (latest version per NDB number): analysed values > 0 replace SR Legacy values
    fnd_latest: dict[str, str] = {}
    for r in sorted(fnd_food, key=lambda x: x["publication_date"]):
        ndb = fnd_ndb.get(r["fdc_id"])
        if ndb:
            fnd_latest[ndb] = r["fdc_id"]
    fnd_raw: dict[str, dict] = defaultdict(dict)
    for r in fnd_nut:
        a = num(r["amount"])
        if a is not None and a > 0:
            fnd_raw[r["fdc_id"]][r["nutrient_id"]] = a
    overlay_count = 0

    portions: dict[str, list[dict]] = defaultdict(list)
    for p in sr_por:
        portions[p["fdc_id"]].append(p)

    foods_all: dict[str, dict] = {}
    for r in sr_food:
        fid = r["fdc_id"]
        cat = sr_cat.get(r["food_category_id"], "")
        prof = profile(raw[fid])
        sources = {}
        f_id = fnd_latest.get(sr_ndb.get(fid, ""))
        if f_id and fnd_raw.get(f_id):
            fp = profile(fnd_raw[f_id])
            if len(fp) >= 10:
                for k, v in fp.items():
                    if k in ("energy",) and "energy" in prof:
                        continue  # keep SR kcal: Foundation often lacks 1008 and uses Atwater-specific ids
                    if k in prof or k in ("potassium", "magnesium", "calcium", "iron", "zinc", "protein", "fat", "carbs", "fiber"):
                        prof[k] = v
                        sources[k] = "F"
                        overlay_count += 1
        foods_all[fid] = {"fdc_id": int(fid), "desc": r["description"], "usda_category": cat,
                          "group": GROUPS.get(cat, "other"), "n": prof, "sources": sources,
                          "fnd_id": int(f_id) if f_id and sources else None}

    # ------------------------------------------------------------ ranking pool
    pool = []
    for f in foods_all.values():
        g, d = f["group"], f["desc"]
        if g not in RANK_GROUPS and g != "fats-oils":
            continue
        if f["usda_category"] == "Breakfast Cereals" and "not fortified" not in d:
            continue
        if EXCLUDE_ALL.search(d) and not (f["usda_category"] == "Breakfast Cereals" and "not fortified" in d):
            continue
        if g in ("fruits", "vegetables") and EXCLUDE_DRIED.search(d) and not d.startswith(("Dates", "Figs, dried", "Plums, dried", "Raisins", "Apricots, dried")):
            continue
        if g in ("fruits", "vegetables") and "canned" in d.lower() and not CANNED_OK.search(d):
            continue
        if g == "grains" and not GRAIN_OK.search(d):
            continue
        if g in ("meat", "fish-seafood", "legumes", "grains") and EXCLUDE_RAW.search(d) and not d.startswith(("Nuts", "Seeds", "Peanut", "Cereals, oats", "Tofu", "Hummus")):
            continue
        if g == "dairy-eggs" and re.search(r"\bdry\b|dried|whey|cream, fluid|half and half|sour cream|eggnog|topping|dessert|pudding|shake|ice cream|frozen|sherbet|yogurt, fruit|yogurt, vanilla|yogurt, chocolate|cheese food|cheese spread|cheese sauce|cheese product|process", d, re.I):
            continue
        if "energy" not in f["n"] or f["n"]["energy"] is None:
            continue
        if EXOTIC.search(d):
            continue
        p = pick_serving(portions[str(f["fdc_id"])], rules_for(g, d))
        if p is None:
            continue
        f["serving"] = serving_dict(p)
        f["family"] = family_key(d)
        f["name"] = pretty(d)
        pool.append(f)
    print(f"ranking pool: {len(pool)} foods")

    # scores (per 100 kcal)
    enc, lim = ndefs["nrf_encourage"], ndefs["nrf_limit"]
    LIMIT_REF = {"sat_fat": 20.0, "sugars": 50.0, "sodium": 2300.0}

    def per100kcal(f: dict, key: str):
        kcal = f["n"].get("energy")
        v = f["n"].get(key)
        if not kcal or kcal < 5 or v is None:
            return None
        return v * 100.0 / kcal

    def nrf(f: dict):
        kcal = f["n"].get("energy")
        if not kcal or kcal < 5:
            return None
        s = 0.0
        for k in enc:
            v = per100kcal(f, k)
            if v is not None:
                s += min(100.0, v / by_key[k]["dv"] * 100.0)
        for k in lim:
            v = per100kcal(f, k)
            if v is not None:
                s -= min(100.0, v / LIMIT_REF[k] * 100.0)
        return round(s, 1)

    def dii(f: dict):
        """Inflammatory nutrient-profile score: sum of DII effect scores weighted by how much of each
        nutrient's reference daily amount a 100 kcal portion supplies (capped at 2x the 100 kcal share)."""
        kcal = f["n"].get("energy")
        if not kcal or kcal < 5:
            return None
        s, used = 0.0, 0
        for n in NUTS:
            w = n.get("dii")
            if w is None:
                continue
            ref = n.get("dv") or n.get("dii_ref")
            v = per100kcal(f, n["key"])
            if v is None or not ref:
                continue
            # ratio 1 = the 100 kcal portion supplies exactly 1/20 of the daily reference amount (a 2,000 kcal day)
            s += w * (min(2.0, v / (ref / 20.0)) - 1.0)
            used += 1
        return round(s, 2) if used >= 8 else None

    for f in pool:
        f["nrf"] = nrf(f)
        f["dii"] = dii(f)
    import bisect
    dii_sorted = sorted(f["dii"] for f in pool if f["dii"] is not None and f["group"] in RANK_GROUPS)

    def dii_pct(v):
        """Percentile of the score among whole foods in the ranking pool: 0 = most anti-inflammatory."""
        if v is None or not dii_sorted:
            return None
        return round(100.0 * bisect.bisect_left(dii_sorted, v) / len(dii_sorted))

    def dii_label(v):
        pc = dii_pct(v)
        if pc is None:
            return None
        return ("strongly anti-inflammatory" if pc < 20 else "anti-inflammatory" if pc < 40
                else "average for whole foods" if pc < 60 else "below average" if pc < 80 else "pro-inflammatory profile")
    for f in pool:
        f["dii_pct"] = dii_pct(f["dii"])
        f["dii_label"] = dii_label(f["dii"])

    # curated food pages
    curated = json.loads((CUR / "foods.json").read_text())
    desc_index = {f["desc"]: f for f in foods_all.values()}

    def resolve(rx: str) -> dict:
        r = re.compile(rx)
        hits = [f for d, f in desc_index.items() if r.search(d)]
        if not hits:
            sys.exit(f"no SR Legacy food matches {rx!r}")
        hits.sort(key=lambda f: len(f["desc"]))
        if len(hits) > 1:
            print(f"  note: {rx!r} matched {len(hits)}; using {hits[0]['desc']!r}")
        return hits[0]

    page_of: dict[int, str] = {}
    foods_out = []
    for c in curated:
        base = resolve(c["match"])
        g = c["group"]
        hint = c.get("serve")
        rules = rules_for(g, base["desc"], hint if hint not in ("halfcup",) else None)
        if hint == "halfcup":
            rules = ["halfcup", "synth_halfcup"] + rules
        if hint == "tbsp2":
            rules = ["tbsp2", "synth_2tbsp"] + rules
        p = pick_serving(portions[str(base["fdc_id"])], rules)
        serving = serving_dict(p)
        ports = []
        for pp in sorted(portions[str(base["fdc_id"])], key=lambda x: int(x["seq_num"] or 0)):
            gw = num(pp["gram_weight"])
            if gw and gw >= 1:
                ports.append({"label": portion_label(pp), "g": gw})
        ports.append({"label": "100 g", "g": 100.0})
        variants = []
        for label, rx in c.get("variants", []):
            v = resolve(rx)
            vp = pick_serving(portions[str(v["fdc_id"])], rules_for(g, v["desc"], hint if hint not in ("halfcup",) else None))
            variants.append({"label": label, "fdc_id": v["fdc_id"], "desc": v["desc"], "n": v["n"],
                             "serving": serving_dict(vp)})
            page_of[v["fdc_id"]] = c["slug"]
        page_of[base["fdc_id"]] = c["slug"]
        fo = {"slug": c["slug"], "name": c["name"], "group": g, "aliases": c.get("aliases", ""),
              "fdc_id": base["fdc_id"], "desc": base["desc"], "usda_category": base["usda_category"],
              "n": base["n"], "sources": base["sources"], "fnd_id": base["fnd_id"], "serving": serving,
              "portions": ports[:8], "variants": variants,
              "nrf": nrf(base), "dii": dii(base)}
        fo["dii_label"] = dii_label(fo["dii"])
        fo["dii_pct"] = dii_pct(fo["dii"])
        for v in variants:
            v["nrf"], v["dii"] = nrf(v), dii(v)
        foods_out.append(fo)
    print(f"curated foods: {len(foods_out)}")

    for f in pool:
        f["page"] = page_of.get(f["fdc_id"])

    # ------------------------------------------------------------ rankings
    def rank_list(cands: list[dict], key: str, reverse=True, cap_family=True, limit=100, per_head=6) -> list[dict]:
        rows = []
        for f in cands:
            v = f["n"].get(key)
            if v is None:
                continue
            per_serv = v * f["serving"]["g"] / 100.0
            rows.append((per_serv, f))
        rows.sort(key=lambda t: (-t[0] if reverse else t[0], -(t[1].get("nrf") or -999), t[1]["desc"]))
        seen_fam, head_count, out = set(), defaultdict(int), []
        for per_serv, f in rows:
            if cap_family:
                if f["family"] in seen_fam:
                    continue
                head = f["family"].split("|")[0]
                if head_count[head] >= per_head:
                    continue
                seen_fam.add(f["family"])
                head_count[head] += 1
            dv = by_key[key].get("dv")
            out.append({"fdc_id": f["fdc_id"], "name": f["name"], "short": short_desc(f["desc"]), "group": f["group"], "page": f.get("page"),
                        "serving": f["serving"]["short"] if not f["serving"].get("fallback") else "100 g",
                        "g": f["serving"]["g"], "amount": round(per_serv, 3), "per100": f["n"][key],
                        "dv": round(per_serv / dv * 100, 1) if dv else None,
                        "kcal": round(f["n"]["energy"] * f["serving"]["g"] / 100.0)})
            if len(out) >= limit:
                break
        return out

    rank_pool = [f for f in pool if f["group"] in RANK_GROUPS]
    rankings = {}
    for key in ndefs["rank_order"]:
        cands = rank_pool
        if key == "caffeine":  # coffee, tea, cocoa live outside the whole-food groups
            extra = [f for f in foods_all.values() if re.match(r"^Beverages, (coffee|tea), .*brewed|^Beverages, Energy|^Chocolate, dark", f["desc"])
                     and "instant" not in f["desc"].lower() and "decaf" not in f["desc"].lower()]
            for f in extra:
                if "serving" not in f:
                    p = pick_serving(portions[str(f["fdc_id"])], ["floz"] if "espresso" in f["desc"] else ["cup", "fl8", "synth_fl8"] if f["desc"].startswith("Beverages") else ["oz", "synth_oz"])
                    if p is None:
                        continue
                    f["serving"], f["family"], f["name"] = serving_dict(p), family_key(f["desc"]), pretty(f["desc"])
                    f["page"] = page_of.get(f["fdc_id"])
            cands = rank_pool + [f for f in extra if "serving" in f]
        if key in ("mono", "poly"):
            cands = rank_pool + [f for f in pool if f["group"] == "fats-oils"]
        entry = {"all": [r for r in rank_list(cands, key, limit=110) if r["amount"] > 0][:100], "groups": {}}
        for g in RANK_GROUPS:
            lst = rank_list([f for f in cands if f["group"] == g], key, limit=50)
            lst = [r for r in lst if r["amount"] > 0]
            if len(lst) >= 8:
                entry["groups"][g] = lst
        rankings[key] = entry
    for key in ndefs["low_pages"]:
        cands = [f for f in rank_pool if (f["n"].get("energy") or 0) >= 20]
        rankings["low_" + key] = {"all": rank_list(cands, key, reverse=False, limit=100), "groups": {}}
        for g in RANK_GROUPS:
            lst = rank_list([f for f in cands if f["group"] == g], key, reverse=False, limit=50)
            if len(lst) >= 8:
                rankings["low_" + key]["groups"][g] = lst

    # ranks for curated foods (position among ranked foods in the same group and overall)
    for fo in foods_out:
        fo["ranks"] = {}
        for key in ndefs["rank_order"]:
            r = rankings[key]
            allpos = next((i + 1 for i, row in enumerate(r["all"]) if row["fdc_id"] == fo["fdc_id"]), None)
            grp = r["groups"].get(fo["group"], [])
            gpos = next((i + 1 for i, row in enumerate(grp) if row["fdc_id"] == fo["fdc_id"]), None)
            if allpos or gpos:
                fo["ranks"][key] = {"all": allpos, "all_n": len(r["all"]), "group": gpos, "group_n": len(grp)}

    # ------------------------------------------------------------ healthiest categories
    hdefs = json.loads((CUR / "healthiest.json").read_text())
    healthiest = {}
    for slug, h in hdefs.items():
        if h.get("pool_group"):
            members = [f for f in pool if f["group"] == h["pool_group"]]
            seen = set()
            mem2 = []
            for f in sorted(members, key=lambda f: -(f["nrf"] or -999)):
                if f["family"] in seen:
                    continue
                seen.add(f["family"])
                mem2.append(f)
            members = mem2
        else:
            inc = re.compile(h["include"]) if h.get("include") else None
            exc = re.compile(h["exclude"], re.I) if h.get("exclude") else None
            members = []
            for f in foods_all.values():
                if h.get("categories") and f["usda_category"] not in h["categories"]:
                    continue
                if inc and not inc.search(f["desc"]):
                    continue
                if exc and exc.search(f["desc"]):
                    continue
                if (f["n"].get("energy") or 0) < h.get("min_kcal", 0):
                    continue
                if "energy" not in f["n"]:
                    continue
                f = dict(f)
                rules = {"oz": ["oz", "synth_oz"], "slice": ["slice", "oz", "synth_oz"], "cup": ["cup", "synth_fl8"],
                         "fl8": ["fl8", "synth_fl8"], "bar": ["bar", "nlea", "item", "oz"], "nlea": ["nlea", "cup", "item"],
                         "item": ["item", "nlea", "cup", "oz"]}[h["serve"]]
                p = pick_serving(portions[str(f["fdc_id"])], rules)
                if p is None and h["serve"] == "fl8":
                    f["serving"] = {"label": "8 fl oz (240 g)", "short": "8 fl oz", "g": 240.0, "fallback": False}
                elif p is None:
                    continue
                else:
                    f["serving"] = serving_dict(p)
                if h["serve"] == "fl8" and abs(f["serving"]["g"] - 240) > 60:
                    f["serving"] = {"label": "8 fl oz (240 g)", "short": "8 fl oz", "g": 240.0, "fallback": False}
                f["name"] = pretty(f["desc"])
                f["family"] = family_key(f["desc"])
                f["nrf"] = nrf(f)
                f["dii"] = dii(f)
                f["page"] = page_of.get(f["fdc_id"])
                members.append(f)
        rows = []
        for f in members:
            g = f["serving"]["g"]
            per = {k: (round(f["n"][k] * g / 100.0, 2) if k in f["n"] else None) for k in h["columns"]}
            if h["score"] == "drink":
                score = -(per.get("sugars") or 0) - (per.get("energy") or 0) / 20.0
            else:
                score = f["nrf"]
                if score is None:
                    continue
                for k in h.get("penalize", []):
                    v = f["n"].get(k)
                    if v is not None and f["n"]["energy"]:
                        score -= min(100.0, (v * 100.0 / f["n"]["energy"]) / LIMIT_REF[k] * 100.0) * 0.1
            rows.append({"fdc_id": f["fdc_id"], "name": f["name"], "short": short_desc(f["desc"]), "page": f.get("page"), "serving": f["serving"]["short"],
                         "g": g, "score": round(score, 1), "nrf": f["nrf"], "dii": f["dii"], "per": per,
                         "kcal": round((f["n"].get("energy") or 0) * g / 100.0)})
        rows.sort(key=lambda r: (-r["score"], r["name"]))
        if h.get("max_per_family"):
            fam_count, kept = defaultdict(int), []
            fam_of = {f["fdc_id"]: f["family"] for f in members}
            for r in rows:
                fam = fam_of[r["fdc_id"]]
                if fam_count[fam] >= h["max_per_family"]:
                    continue
                fam_count[fam] += 1
                kept.append(r)
            rows = kept
        for i, r in enumerate(rows, 1):
            r["rank"] = i
            r["dii_label"] = dii_label(r["dii"])
        healthiest[slug] = {**{k: v for k, v in h.items() if k in ("name", "noun", "intro", "columns", "score", "penalize")},
                            "rows": rows[:60], "total": len(rows)}
        print(f"  healthiest/{slug}: {len(rows)} items")

    # ------------------------------------------------------------ category stats
    cats = {}
    for g in RANK_GROUPS:
        members = [f for f in rank_pool if f["group"] == g]
        stats = {}
        for key in ndefs["rank_order"]:
            vals = [f["n"][key] * f["serving"]["g"] / 100 for f in members if key in f["n"]]
            if len(vals) >= 5:
                top = rankings[key]["groups"].get(g, [])
                stats[key] = {"median": round(statistics.median(vals), 3), "n": len(vals),
                              "top": top[0] if top else None}
        cats[g] = {"slug": g, "name": GROUP_NAMES[g], "count": len(members),
                   "pages": [fo["slug"] for fo in foods_out if fo["group"] == g], "stats": stats,
                   "sample": sorted({f["family"].split("|")[0].capitalize() for f in members})[:40]}

    # ------------------------------------------------------------ write
    OUT.mkdir(exist_ok=True)
    (OUT / "nutrients.json").write_text(json.dumps(ndefs, indent=1, ensure_ascii=False))
    (OUT / "foods.json").write_text(json.dumps(foods_out, indent=0, ensure_ascii=False))
    slim_pool = [{k: f[k] for k in ("fdc_id", "name", "group", "family", "serving", "n", "nrf", "dii", "dii_pct", "dii_label", "page")} for f in pool]
    (OUT / "pool.json").write_text(json.dumps(slim_pool, separators=(",", ":"), ensure_ascii=False))
    (OUT / "rankings.json").write_text(json.dumps(rankings, separators=(",", ":"), ensure_ascii=False))
    (OUT / "healthiest.json").write_text(json.dumps(healthiest, indent=0, ensure_ascii=False))
    (OUT / "categories.json").write_text(json.dumps(cats, indent=0, ensure_ascii=False))
    (OUT / "meta.json").write_text(json.dumps({
        "sr_release": SR_RELEASE, "fnd_release": FND_RELEASE, "sr_foods": len(sr_food),
        "fnd_foods": len(fnd_latest), "pool": len(pool), "overlay_values": overlay_count,
        "curated": len(foods_out), "group_names": GROUP_NAMES, "rank_groups": RANK_GROUPS}, indent=1))
    print(f"wrote data/*.json  (Foundation overlay: {overlay_count} values on {sum(1 for f in foods_all.values() if f['sources'])} foods)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
