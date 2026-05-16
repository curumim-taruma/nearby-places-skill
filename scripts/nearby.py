#!/usr/bin/env python3
"""List OpenStreetMap places within a radius of a lat/lon (default 100 m)."""

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
    fetch_nearby,
    reverse_geocode,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="List OSM places near a coordinate.")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius", type=int, default=DEFAULT_RADIUS_M)
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_RESULTS, dest="max_results")
    parser.add_argument("--focus", choices=["all", "tourist"], default="all")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    parser.add_argument("--no-geocode", action="store_true")
    args = parser.parse_args()

    if args.radius < 1 or args.radius > 2000:
        print("radius must be between 1 and 2000 meters", file=sys.stderr)
        return 2

    try:
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

    address = None if args.no_geocode else reverse_geocode(args.lat, args.lon)
    title = "Tourist & historic nearby" if args.focus == "tourist" else "Nearby places"

    if args.json:
        out = {
            "lat": args.lat,
            "lon": args.lon,
            "radius_m": args.radius,
            "focus": args.focus,
            "address": address,
            "count": len(places),
            "places": [{k: v for k, v in p.items() if k != "tags"} for p in places],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(args.lat, args.lon, args.radius, address, places, title=title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
