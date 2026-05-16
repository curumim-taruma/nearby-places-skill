#!/usr/bin/env python3
"""List OpenStreetMap places within a radius of a lat/lon."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from osm_core import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_RADIUS_M,
    PIN_HIGHLIGHT_MAX,
    PIN_HIGHLIGHT_MIN_DISTANCE_M,
    PIN_HIGHLIGHT_RADIUS_M,
    PIN_IMMEDIATE_MAX,
    PIN_IMMEDIATE_RADIUS_M,
    fetch_nearby,
    reverse_geocode,
)
from place_enrich import (
    attach_details,
    dedupe_against,
    is_notable_tourist,
    is_pin_worthy,
    sort_pin_places,
    tourist_priority,
)


def format_markdown(
    lat: float,
    lon: float,
    radius_m: int,
    address: str | None,
    places: list[dict[str, Any]],
    *,
    title: str = "Nearby places",
) -> str:
    lines = [f"**{title}** (within **{radius_m} m**)", f"📍 {lat:.6f}, {lon:.6f}"]
    if address:
        lines.append(f"_{address}_")
    lines.append("")

    if not places:
        lines.append(
            "_No places found in OpenStreetMap for this radius. "
            "Try a larger radius or share live location again._"
        )
        return "\n".join(lines)

    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in places:
        by_cat[p["category"]].append(p)

    for category in sorted(by_cat, key=lambda c: (min(x["distance_m"] for x in by_cat[c]), c)):
        lines.append(f"**{category}**")
        for p in by_cat[category]:
            lines.append(f"- {p['name']} — **{p['distance_m']} m**")
        lines.append("")

    lines.append(f"_Source: OpenStreetMap · {len(places)} place(s)_")
    return "\n".join(lines).rstrip()


def _format_place_line(p: dict[str, Any]) -> str:
    emoji = p.get("emoji") or ("🏛" if p.get("kind") == "tourist" else "🍽" if p.get("kind") == "food" else "📍")
    line = f"{emoji} **{p['name']}** — {p['distance_m']} m"
    detail = p.get("detail")
    if detail:
        line += f"\n   _{detail}_"
    summary = p.get("summary")
    if summary:
        line += f"\n   {summary}"
    return line


def format_pin_markdown(
    lat: float,
    lon: float,
    address: str | None,
    immediate: list[dict[str, Any]],
    highlight: list[dict[str, Any]],
    *,
    immediate_radius_m: int,
    highlight_radius_m: int,
) -> str:
    lines = [
        "**Right where you are**",
        f"📍 {lat:.6f}, {lon:.6f} · ~{immediate_radius_m} m (no direction — closest first)",
    ]
    if address:
        lines.append(f"_{address}_")
    lines.append("")

    if immediate:
        for p in immediate:
            lines.append(_format_place_line(p))
    else:
        lines.append("_Nothing mapped this close — try stepping toward the street or a storefront._")

    lines.append("")
    lines.append(f"**Notable a bit further** (~{highlight_radius_m} m)")
    if highlight:
        for p in highlight:
            lines.append(_format_place_line(p))
    else:
        lines.append("_No major tourist landmark a few blocks away in OpenStreetMap._")

    lines.append("")
    lines.append(
        "_Historic sights listed first. Restaurants show cuisine/type from map data; "
        "star ratings only when tagged in OSM (most are not)._"
    )
    lines.append("_Source: OpenStreetMap_")
    return "\n".join(lines).rstrip()


def fetch_pin_report(
    lat: float,
    lon: float,
    *,
    immediate_radius_m: int = PIN_IMMEDIATE_RADIUS_M,
    highlight_radius_m: int = PIN_HIGHLIGHT_RADIUS_M,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Immediate ring + wider ring for notable tourist only."""
    raw_immediate = fetch_nearby(
        lat,
        lon,
        immediate_radius_m,
        focus="all",
        max_results=PIN_IMMEDIATE_MAX + 16,
    )
    worthy = [p for p in raw_immediate if is_pin_worthy(p["name"], p.get("tags") or {})]
    immediate = attach_details(sort_pin_places(worthy))[:PIN_IMMEDIATE_MAX]
    seen = {p["name"].casefold() for p in immediate}

    raw_far = fetch_nearby(
        lat,
        lon,
        highlight_radius_m,
        focus="tourist",
        max_results=PIN_HIGHLIGHT_MAX + 10,
    )
    far_filtered = [
        p
        for p in raw_far
        if p["distance_m"] >= PIN_HIGHLIGHT_MIN_DISTANCE_M
        and is_notable_tourist(p.get("tags") or {}, p["name"])
    ]
    far_sorted = sorted(
        far_filtered,
        key=lambda p: (-tourist_priority(p.get("tags") or {}), p["distance_m"]),
    )
    highlight = attach_details(dedupe_against(far_sorted, seen_names=seen))[:PIN_HIGHLIGHT_MAX]
    return immediate, highlight


def main() -> int:
    parser = argparse.ArgumentParser(description="List OSM places near a coordinate.")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius", type=int, default=DEFAULT_RADIUS_M)
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_RESULTS, dest="max_results")
    parser.add_argument("--focus", choices=["all", "tourist"], default="all")
    parser.add_argument(
        "--mode",
        choices=["pin", "legacy"],
        default="pin",
        help="pin: close + highlights (default for location pins); legacy: single-radius list",
    )
    parser.add_argument("--immediate-radius", type=int, default=PIN_IMMEDIATE_RADIUS_M)
    parser.add_argument("--highlight-radius", type=int, default=PIN_HIGHLIGHT_RADIUS_M)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    parser.add_argument("--no-geocode", action="store_true")
    args = parser.parse_args()

    if args.radius < 1 or args.radius > 2000:
        print("radius must be between 1 and 2000 meters", file=sys.stderr)
        return 2

    address = None if args.no_geocode else reverse_geocode(args.lat, args.lon)

    try:
        if args.mode == "pin":
            immediate, highlight = fetch_pin_report(
                args.lat,
                args.lon,
                immediate_radius_m=args.immediate_radius,
                highlight_radius_m=args.highlight_radius,
            )
        else:
            places = fetch_nearby(
                args.lat,
                args.lon,
                args.radius,
                focus=args.focus,
                max_results=args.max_results,
            )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        if args.mode == "pin":
            out = {
                "lat": args.lat,
                "lon": args.lon,
                "mode": "pin",
                "address": address,
                "immediate_radius_m": args.immediate_radius,
                "highlight_radius_m": args.highlight_radius,
                "immediate": immediate,
                "highlight": highlight,
            }
        else:
            out = {
                "lat": args.lat,
                "lon": args.lon,
                "mode": "legacy",
                "radius_m": args.radius,
                "focus": args.focus,
                "address": address,
                "count": len(places),
                "places": [{k: v for k, v in p.items() if k != "tags"} for p in places],
            }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.mode == "pin":
        print(
            format_pin_markdown(
                args.lat,
                args.lon,
                address,
                immediate,
                highlight,
                immediate_radius_m=args.immediate_radius,
                highlight_radius_m=args.highlight_radius,
            )
        )
    else:
        title = "Tourist & historic nearby" if args.focus == "tourist" else "Nearby places"
        print(format_markdown(args.lat, args.lon, args.radius, address, places, title=title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
