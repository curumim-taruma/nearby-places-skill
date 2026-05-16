"""Classify, score, and describe places for single-location (pin) replies."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from osm_core import USER_AGENT, is_tourist_poi

_WIKIDATA_CACHE: dict[str, str | None] = {}

# Chains where cuisine/type is obvious — skip long food descriptions.
OBVIOUS_CHAIN_NAMES = frozenset(
    {
        "mcdonald's",
        "mcdonalds",
        "burger king",
        "subway",
        "kfc",
        "starbucks",
        "domino's",
        "dominos",
        "pizza hut",
        "taco bell",
        "wendy's",
        "dunkin",
        "dunkin donuts",
        "baskin-robbins",
        "häagen-dazs",
        "haagen dazs",
        "chipotle",
        "five guys",
        "popeyes",
        "tim hortons",
        "jollibee",
        "habib's",
        "habibs",
        "bob's",
        "outback steakhouse",
        "applebee's",
        "denny's",
        "ihop",
        "olive garden",
        "red lobster",
        "buffalo wild wings",
        "panda express",
        "little caesars",
        "a&w",
        "carl's jr",
        "hardee's",
        "sonic drive-in",
        "jack in the box",
        "in-n-out",
        "shake shack",
        "pret a manger",
        "costa coffee",
        "greggs",
    }
)

FOOD_AMENITIES = frozenset(
    {"restaurant", "fast_food", "cafe", "food_court", "biergarten", "bar", "pub", "ice_cream"}
)

NOTABLE_TOURISM = frozenset(
    {
        "museum",
        "attraction",
        "artwork",
        "viewpoint",
        "theme_park",
        "zoo",
        "aquarium",
        "gallery",
        "monument",
        "archaeological_site",
        "castle",
        "ruins",
        "palace",
        "fort",
        "tower",
    }
)

NOTABLE_HISTORIC = frozenset(
    {
        "monument",
        "memorial",
        "castle",
        "ruins",
        "archaeological_site",
        "building",
        "church",
        "city_gate",
        "fort",
        "manor",
        "palace",
        "tomb",
        "wayside_cross",
        "tower",
    }
)

CUISINE_LABELS: dict[str, str] = {
    "pizza": "pizza",
    "italian": "Italian",
    "japanese": "Japanese",
    "sushi": "sushi",
    "chinese": "Chinese",
    "mexican": "Mexican",
    "burger": "burgers",
    "hamburger": "burgers",
    "seafood": "seafood",
    "steak_house": "steakhouse",
    "steak": "steakhouse",
    "regional": "regional cuisine",
    "brazilian": "Brazilian",
    "portuguese": "Portuguese",
    "french": "French",
    "indian": "Indian",
    "thai": "Thai",
    "korean": "Korean",
    "vietnamese": "Vietnamese",
    "greek": "Greek",
    "spanish": "Spanish",
    "tapas": "tapas",
    "middle_eastern": "Middle Eastern",
    "lebanese": "Lebanese",
    "turkish": "Turkish",
    "arab": "Arab",
    "vegetarian": "vegetarian",
    "vegan": "vegan",
    "barbecue": "barbecue",
    "bbq": "barbecue",
    "chicken": "chicken",
    "sandwich": "sandwiches",
    "coffee_shop": "coffee",
    "coffee": "coffee",
    "ice_cream": "ice cream",
    "donut": "donuts",
    "doughnut": "donuts",
    "pasta": "pasta",
    "ramen": "ramen",
    "noodle": "noodles",
    "fish": "fish",
    "fish_and_chips": "fish and chips",
    "taco": "tacos",
    "kebab": "kebab",
    "local": "local cuisine",
}


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().casefold())


def is_food_place(tags: dict[str, str]) -> bool:
    amenity = (tags.get("amenity") or "").strip()
    if amenity in FOOD_AMENITIES:
        return True
    shop = (tags.get("shop") or "").strip()
    return shop in {"bakery", "confectionery", "pastry"}


def is_obvious_chain(name: str, tags: dict[str, str]) -> bool:
    brand = _norm_name(tags.get("brand") or "")
    nm = _norm_name(name)
    if brand and brand in OBVIOUS_CHAIN_NAMES:
        return True
    if nm in OBVIOUS_CHAIN_NAMES:
        return True
    for chain in OBVIOUS_CHAIN_NAMES:
        if chain in nm or (brand and chain in brand):
            return True
    return tags.get("brand:wikidata") in {
        "Q38076",
        "Q177837",
        "Q38076",
    }  # McDonald's wikidata etc. — optional


def format_cuisine(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    parts: list[str] = []
    for token in re.split(r"[;,|]", raw):
        key = token.strip().casefold().replace("-", "_")
        if not key:
            continue
        label = CUISINE_LABELS.get(key, key.replace("_", " "))
        if label not in parts:
            parts.append(label)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:3])


def format_rating(tags: dict[str, str]) -> str | None:
    michelin = (tags.get("award:michelin") or tags.get("stars:michelin") or "").strip()
    if michelin and michelin not in {"no", "0"}:
        return f"Michelin {michelin.replace('_', ' ')}"

    stars = (tags.get("stars") or "").strip()
    if stars and stars not in {"yes", "no"}:
        return f"{stars}★ (map data)"

    rating = (tags.get("rating") or tags.get("rate:stars") or "").strip()
    if rating and rating.replace(".", "", 1).isdigit():
        return f"{rating}/5 (map data)"

    return None


def restaurant_detail(name: str, tags: dict[str, str]) -> str | None:
    if not is_food_place(tags):
        return None

    if is_obvious_chain(name, tags):
        brand = (tags.get("brand") or name).replace("_", " ").strip()
        amenity = (tags.get("amenity") or "").replace("_", " ")
        kind = "fast-food chain" if amenity == "fast food" or tags.get("amenity") == "fast_food" else "chain"
        return f"{brand} ({kind})"

    parts: list[str] = []
    cuisine = format_cuisine(tags.get("cuisine"))
    amenity = (tags.get("amenity") or "").replace("_", " ")
    if cuisine:
        parts.append(cuisine)
    elif amenity == "fast_food":
        parts.append("fast food")
    elif amenity == "cafe":
        parts.append("café")
    elif amenity == "bar":
        parts.append("bar")
    elif amenity == "pub":
        parts.append("pub")
    elif amenity == "restaurant":
        parts.append("restaurant")

    rating = format_rating(tags)
    if rating:
        parts.append(rating)

    if tags.get("diet:vegetarian") == "only":
        parts.append("vegetarian only")
    elif tags.get("diet:vegan") == "only":
        parts.append("vegan only")

    takeaway = tags.get("takeaway")
    if takeaway == "only":
        parts.append("takeaway only")

    if not parts:
        return "restaurant"
    return " · ".join(parts)


def tourist_priority(tags: dict[str, str]) -> int:
    if not is_tourist_poi(tags):
        return 0
    score = 100
    tourism = (tags.get("tourism") or "").strip()
    historic = (tags.get("historic") or "").strip()
    if tourism in NOTABLE_TOURISM:
        score += 80
    if historic in NOTABLE_HISTORIC:
        score += 70
    if tags.get("heritage"):
        score += 60
    if tags.get("wikidata"):
        score += 40
    if tags.get("wikipedia") or tags.get("wikipedia:pt") or tags.get("wikipedia:en"):
        score += 30
    if (tags.get("building") or "") in {"cathedral", "church", "mosque", "temple", "chapel", "monastery"}:
        score += 50
    if tags.get("memorial"):
        score += 40
    return score


def is_notable_tourist(tags: dict[str, str], name: str = "") -> bool:
    if not is_tourist_poi(tags):
        return False
    if name and not has_distinct_name(name, tags):
        return False
    return tourist_priority(tags) >= 140


PIN_SKIP_AMENITIES = frozenset(
    {
        "bench",
        "waste_basket",
        "recycling",
        "bicycle_parking",
        "motorcycle_parking",
        "parking",
        "parking_space",
        "vending_machine",
        "drinking_water",
        "fountain",
        "clock",
        "shelter",
        "grit_bin",
        "post_box",
        "telephone",
        "charging_station",
    }
)

PIN_SKIP_BUILDINGS = frozenset({"roof", "yes", "garage", "shed", "hut", "carport"})

PIN_SKIP_SHOPS = frozenset({"ticket", "ticket;lottery", "lottery"})

GENERIC_PLACE_NAMES = frozenset(
    {
        "attraction",
        "monument",
        "memorial",
        "artwork",
        "museum",
        "historic",
        "yes",
        "roof",
        "bench",
        "waste basket",
        "place",
    }
)


def has_distinct_name(name: str, tags: dict[str, str]) -> bool:
    if (tags.get("name") or "").strip():
        return True
    if (tags.get("brand") or "").strip():
        return True
    return name.casefold() not in GENERIC_PLACE_NAMES


def is_pin_worthy(name: str, tags: dict[str, str]) -> bool:
    """Drop noise for the immediate (~35 m) ring."""
    amenity = (tags.get("amenity") or "").strip()
    if amenity in PIN_SKIP_AMENITIES:
        return False

    building = (tags.get("building") or "").strip()
    if building in PIN_SKIP_BUILDINGS:
        return False

    shop = (tags.get("shop") or "").strip()
    if shop in PIN_SKIP_SHOPS:
        return False

    tourism = (tags.get("tourism") or "").strip()
    if tourism == "information" and not tags.get("historic") and not tags.get("artwork_type"):
        return False

    if tags.get("highway") and tags.get("highway") not in {"bus_stop", "tram_stop"}:
        return False

    if not is_tourist_poi(tags) and not is_food_place(tags):
        if (tags.get("office") or tags.get("craft")) and not tags.get("tourism"):
            return False
        cat_keys = ("amenity", "shop", "tourism", "historic", "leisure")
        if not any((tags.get(k) or "").strip() for k in cat_keys):
            return False
        if not has_distinct_name(name, tags):
            return False

    if is_tourist_poi(tags) and not has_distinct_name(name, tags):
        return tourist_priority(tags) >= 180

    return True


def place_kind(tags: dict[str, str]) -> str:
    if is_tourist_poi(tags):
        return "tourist"
    if is_food_place(tags):
        return "food"
    return "other"


def sort_pin_places(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(p: dict[str, Any]) -> tuple[int, int, str]:
        tags = p.get("tags") or {}
        kind = place_kind(tags)
        kind_order = {"tourist": 0, "food": 1, "other": 2}[kind]
        priority = tourist_priority(tags) if kind == "tourist" else 0
        return (kind_order, -priority, p["distance_m"], p["name"].casefold())

    return sorted(places, key=key)


def wikidata_blurb(qid: str, *, lang: str = "en") -> str | None:
    qid = qid.strip()
    if not qid.startswith("Q"):
        return None
    if qid in _WIKIDATA_CACHE:
        return _WIKIDATA_CACHE[qid]

    url = f"https://www.wikidata.org/wiki/Special:EntityData/{urllib.parse.quote(qid)}.json"
    blurb: str | None = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        entity = payload.get("entities", {}).get(qid, {})
        descs = entity.get("descriptions") or {}
        for code in (lang, "en", "pt", "es"):
            if code in descs:
                blurb = (descs[code].get("value") or "").strip() or None
                break
    except Exception:
        blurb = None

    _WIKIDATA_CACHE[qid] = blurb
    return blurb


def attach_details(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in places:
        tags = p.get("tags") or {}
        detail = restaurant_detail(p["name"], tags) if place_kind(tags) == "food" else None
        enriched = {k: v for k, v in p.items() if k != "tags"}
        enriched["kind"] = place_kind(tags)
        enriched["priority"] = tourist_priority(tags)
        if detail:
            enriched["detail"] = detail
        qid = tags.get("wikidata")
        if qid:
            enriched["wikidata"] = qid
            if enriched["kind"] == "tourist":
                summary = wikidata_blurb(str(qid))
                if summary:
                    enriched["summary"] = summary
        out.append(enriched)
    return out


def dedupe_against(places: list[dict[str, Any]], *, seen_names: set[str] | None = None) -> list[dict[str, Any]]:
    seen = set(seen_names or ())
    out: list[dict[str, Any]] = []
    for p in places:
        key = p["name"].casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out
