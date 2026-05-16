"""Shared OpenStreetMap nearby-place lookup (Overpass + Nominatim)."""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_RADIUS_M = 100
DEFAULT_MAX_RESULTS = 40
OVERPASS_URLS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = os.environ.get(
    "NEARBY_PLACES_USER_AGENT",
    "OpenClaw-nearby-places/1.0 (https://github.com/curumim-taruma/nearby-places-skill)",
)

POI_TAG_KEYS = (
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "healthcare",
    "office",
    "craft",
    "historic",
    "public_transport",
    "railway",
    "building",
)

TOURIST_TAG_KEYS = (
    "tourism",
    "historic",
    "heritage",
    "amenity",
    "building",
    "man_made",
    "memorial",
)

HIGHWAY_POI_VALUES = frozenset({"bus_stop", "platform", "tram_stop", "elevator"})

SKIP_TAG_VALUES = frozenset(
    {
        "yes",
        "no",
        "footway",
        "path",
        "steps",
        "crossing",
        "service",
        "track",
        "residential",
        "tertiary",
        "secondary",
        "primary",
        "unclassified",
    }
)

TOURIST_AMENITY_VALUES = frozenset(
    {
        "museum",
        "theatre",
        "arts_centre",
        "place_of_worship",
        "monastery",
        "library",
    }
)

TOURISM_SKIP_VALUES = frozenset({"information", "yes", "no"})


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_json(url: str, *, data: bytes | None = None, timeout: int = 45) -> Any:
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reverse_geocode(lat: float, lon: float) -> str | None:
    params = urllib.parse.urlencode(
        {
            "lat": f"{lat:.7f}",
            "lon": f"{lon:.7f}",
            "format": "json",
            "zoom": 18,
            "addressdetails": 1,
        }
    )
    try:
        payload = fetch_json(f"{NOMINATIM_REVERSE_URL}?{params}", timeout=20)
    except Exception:
        return None
    display = (payload.get("display_name") or "").strip()
    return display or None


def overpass_query(lat: float, lon: float, radius_m: int, *, focus: str = "all") -> str:
    r = int(radius_m)
    selectors: list[str] = []
    if focus == "tourist":
        for key in TOURIST_TAG_KEYS:
            selectors.append(f'  node(around:{r},{lat},{lon})["{key}"];')
            selectors.append(f'  way(around:{r},{lat},{lon})["{key}"];')
        for hw in sorted(HIGHWAY_POI_VALUES):
            selectors.append(f'  node(around:{r},{lat},{lon})["highway"="{hw}"];')
    else:
        for key in POI_TAG_KEYS:
            selectors.append(f'  node(around:{r},{lat},{lon})["{key}"];')
            selectors.append(f'  way(around:{r},{lat},{lon})["{key}"];')
        for hw in sorted(HIGHWAY_POI_VALUES):
            selectors.append(f'  node(around:{r},{lat},{lon})["highway"="{hw}"];')
    body = "\n".join(selectors)
    return f"""[out:json][timeout:25];
(
{body}
);
out center tags;"""


def query_overpass(lat: float, lon: float, radius_m: int, *, focus: str = "all") -> dict[str, Any]:
    if os.environ.get("OVERPASS_URL"):
        urls = [os.environ["OVERPASS_URL"]]
    else:
        urls = list(OVERPASS_URLS)
    query = overpass_query(lat, lon, radius_m, focus=focus)
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    errors: list[str] = []
    for url in urls:
        try:
            return fetch_json(url, data=body, timeout=35)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Overpass query failed:\n" + "\n".join(errors))


def element_coords(el: dict[str, Any]) -> tuple[float, float] | None:
    if el.get("type") == "node":
        lat, lon = el.get("lat"), el.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)
        return None
    center = el.get("center") or {}
    lat, lon = center.get("lat"), center.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lat), float(lon)
    return None


def classify(tags: dict[str, str]) -> str:
    for key in (
        "amenity",
        "shop",
        "tourism",
        "leisure",
        "healthcare",
        "office",
        "craft",
        "historic",
        "heritage",
        "public_transport",
        "railway",
        "highway",
        "building",
        "man_made",
        "memorial",
        "natural",
    ):
        if key in tags:
            value = tags[key].replace("_", " ")
            label = key.replace("_", " ").title()
            return f"{label}: {value}"
    if tags.get("name"):
        return "Place"
    return "Other"


def is_useful_poi(tags: dict[str, str], *, focus: str = "all") -> bool:
    if focus == "tourist":
        return is_tourist_poi(tags)
    if tags.get("highway") and tags.get("highway") not in HIGHWAY_POI_VALUES:
        return False
    for key in POI_TAG_KEYS:
        val = (tags.get(key) or "").strip()
        if val and val not in SKIP_TAG_VALUES:
            return True
    if tags.get("highway") in HIGHWAY_POI_VALUES:
        return True
    return bool((tags.get("name") or "").strip())


def is_tourist_poi(tags: dict[str, str]) -> bool:
    tourism = (tags.get("tourism") or "").strip()
    if tourism and tourism not in TOURISM_SKIP_VALUES:
        return True
    historic = (tags.get("historic") or "").strip()
    if historic and historic not in SKIP_TAG_VALUES:
        return True
    heritage = (tags.get("heritage") or "").strip()
    if heritage and heritage not in SKIP_TAG_VALUES:
        return True
    amenity = (tags.get("amenity") or "").strip()
    if amenity in TOURIST_AMENITY_VALUES:
        return True
    building = (tags.get("building") or "").strip()
    if building in {"church", "cathedral", "mosque", "temple", "chapel", "monastery"}:
        return bool((tags.get("name") or "").strip())
    man_made = (tags.get("man_made") or "").strip()
    if man_made in {"tower", "obelisk", "statue"} and (historic or tourism or tags.get("name")):
        return True
    memorial = (tags.get("memorial") or "").strip()
    if memorial and memorial not in SKIP_TAG_VALUES:
        return True
    return False


def pick_name(tags: dict[str, str]) -> str | None:
    for key in ("name", "brand", "operator", "alt_name"):
        val = (tags.get(key) or "").strip()
        if val:
            return val
    keys = (*POI_TAG_KEYS, *TOURIST_TAG_KEYS, "highway")
    for key in keys:
        val = (tags.get(key) or "").strip()
        if val and val not in SKIP_TAG_VALUES:
            return val.replace("_", " ").title()
    return None


def tourist_emoji(tags: dict[str, str], category: str) -> str:
    cat = category.lower()
    if "museum" in cat or "attraction" in cat or "gallery" in cat:
        return "🏛"
    if "historic" in cat or "heritage" in cat or "archaeological" in cat:
        return "🏺"
    if "memorial" in cat or "monument" in cat:
        return "🗿"
    if "artwork" in cat:
        return "🎨"
    if "worship" in cat or tags.get("building") in {"church", "cathedral", "mosque", "temple", "chapel"}:
        return "⛪"
    if "viewpoint" in cat:
        return "👀"
    if "theme_park" in cat or "zoo" in cat:
        return "🎡"
    return "📍"


def parse_places(
    payload: dict[str, Any],
    lat: float,
    lon: float,
    radius_m: int,
    max_results: int = DEFAULT_MAX_RESULTS,
    *,
    focus: str = "all",
) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    places: list[dict[str, Any]] = []

    for el in payload.get("elements") or []:
        if not isinstance(el, dict):
            continue
        el_id = el.get("id")
        el_type = el.get("type")
        if not isinstance(el_id, int) or not isinstance(el_type, str):
            continue
        key = (el_type, el_id)
        if key in seen:
            continue
        seen.add(key)

        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        if not is_useful_poi(tags, focus=focus):
            continue
        name = pick_name(tags)
        if not name:
            continue

        coords = element_coords(el)
        if not coords:
            continue
        elat, elon = coords
        dist = haversine_m(lat, lon, elat, elon)
        if dist > radius_m:
            continue

        category = classify(tags)
        places.append(
            {
                "name": name,
                "category": category,
                "distance_m": round(dist),
                "lat": elat,
                "lon": elon,
                "osm": f"{el_type}/{el_id}",
                "emoji": tourist_emoji(tags, category) if focus == "tourist" else "📍",
                "tags": tags,
            }
        )

    places.sort(key=lambda p: (p["distance_m"], p["name"].lower()))

    deduped: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for p in places:
        key = p["name"].casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        deduped.append(p)
    return deduped[:max_results] if max_results > 0 else deduped


def fetch_nearby(
    lat: float,
    lon: float,
    radius_m: int = DEFAULT_RADIUS_M,
    *,
    focus: str = "all",
    max_results: int = DEFAULT_MAX_RESULTS,
) -> list[dict[str, Any]]:
    payload = query_overpass(lat, lon, radius_m, focus=focus)
    return parse_places(payload, lat, lon, radius_m, max_results, focus=focus)
