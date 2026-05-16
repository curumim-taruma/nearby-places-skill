---
name: nearby-places
description: Lists shops, restaurants, transit, and tourist/historic places near the user. Use for Telegram location pins, live location, what's around me, o que tem perto, walking tour / modo passeio / guia turístico, or continuous alerts while walking.
tags: [location, telegram, maps, osm, nearby, walk, tourist]
metadata:
  openclaw:
    emoji: "📍"
    requires:
      bins: ["python3", "curl", "openclaw"]
---

# Nearby Places

Answer **“what’s around me?”** and **walking-tour guides** using Telegram location + **OpenStreetMap**.

## Paths

Set **`SKILL_ROOT`** to this skill directory (folder containing `SKILL.md`). All script paths below use:

`python3 "${SKILL_ROOT}/scripts/nearby.py" …`

If unset, substitute the absolute path to your install (e.g. `…/workspace/skills/nearby-places`).

**Walk-mode state:** `OPENCLAW_WORKSPACE/location_walk/sessions/<chat_id>.json` (see README).

## Modes

| Mode | Trigger | Behavior |
|------|---------|----------|
| **One-shot (pin)** | Single location pin or “what’s in front of me?” | **~35 m** immediate ring + **~450 m** notable sights |
| **Walk guide** | `modo passeio`, `walk guide`, `/walk` + **live location** | Automatic alerts every **100 m** or **5 min** for **tourist/historic** POIs |

---

## One-shot (pin or single ask)

1. Read coordinates from `Location` metadata (`latitude`, `longitude`) or coordinate text in the message.
2. Run with the **absolute script path** (required for exec allowlist — do **not** use `cd … &&`):

```bash
python3 "${SKILL_ROOT}/scripts/nearby.py" --lat <LAT> --lon <LON>
```

Default **`--mode pin`** (no extra flags needed):

| Section | Radius | Content |
|---------|--------|---------|
| **Right where you are** | **35 m** | Closest first; **historic/tourist before** restaurants/shops; restaurants show **cuisine/type** (and **rating** when tagged in OSM) |
| **Notable a bit further** | **450 m** | Major tourist/historic only (museums, monuments, heritage, wikidata landmarks) |

Chains like McDonald’s get a short label only. No direction — user may be facing any way.

Legacy single-radius list:

```bash
python3 "${SKILL_ROOT}/scripts/nearby.py" --lat <LAT> --lon <LON> --mode legacy --radius 100
```

3. Reply with script output. Do not invent places or ratings.

---

## Walk guide (live location while walking)

**Requires** the **`walk-guide` hook** enabled (`openclaw hooks enable walk-guide`) and a **gateway restart**.

Install the hook from this repo: copy `hooks/walk-guide/` → `workspace/hooks/walk-guide/`.

### User flow

1. User says **`modo passeio`**, **`walk guide`**, or **`/walk`**.
2. User shares **live location** on Telegram (attachment → Location → share live location for 15 min / 1 h / 8 h).
3. While they walk, the hook calls `walk_guide.py` on each location update and sends **Telegram messages** with **new** tourist/historic spots (no LLM per ping).
4. User says **`parar passeio`** or **`/stop-walk`** to end.

### Agent responsibilities

| Situation | Action |
|-----------|--------|
| User wants walk mode | Confirm hook is enabled; tell them to share **live location**; optionally run `python3 "${SKILL_ROOT}/scripts/walk_guide.py" start --chat-id <CHAT_ID>` |
| User asks to stop | `python3 "${SKILL_ROOT}/scripts/walk_guide.py" stop --chat-id <CHAT_ID>` or tell them `parar passeio` |
| Live location only (walk active) | **Do not** run the full agent pipeline for POI spam — the hook already notified them. Reply only if they also asked a question in text. |
| User wants different thresholds | `start` with `--min-interval 180 --min-distance 80 --radius 200` |

**Chat ID:** numeric Telegram user id (from session key `agent:main:telegram:direct:<id>` or metadata `senderId`).

### Defaults (walk mode)

| Setting | Default |
|---------|---------|
| Search radius | **150 m** |
| Min movement | **100 m** before new lookup |
| Min time | **300 s** (5 min) between alerts |
| Focus | `tourist` (museums, historic, monuments, artwork, churches, attractions) |

### Scripts

```bash
python3 "${SKILL_ROOT}/scripts/walk_guide.py" start --chat-id <CHAT_ID> [--lat LAT --lon LON]
python3 "${SKILL_ROOT}/scripts/walk_guide.py" stop --chat-id <CHAT_ID>
python3 "${SKILL_ROOT}/scripts/walk_guide.py" status --chat-id <CHAT_ID>
python3 "${SKILL_ROOT}/scripts/walk_guide.py" update --chat-id <CHAT_ID> --lat LAT --lon LON
```

---

## Script reference (`nearby.py`)

| Flag | Meaning |
|------|---------|
| `--lat`, `--lon` | Required WGS84 coordinates |
| `--mode` | `pin` (default) or `legacy` |
| `--immediate-radius` | Pin mode close ring (default **35** m) |
| `--highlight-radius` | Pin mode wider ring (default **450** m) |
| `--radius` | Legacy mode only (default **100**, max **2000**) |
| `--focus` | Legacy mode: `all` or `tourist` |
| `--json` | JSON output |
| `--no-geocode` | Skip reverse geocoding |

**Env:** `OVERPASS_URL` — optional single Overpass endpoint. `NEARBY_PLACES_USER_AGENT` — optional OSM User-Agent.

---

## Exec allowlist

Gateway uses `tools.exec.security: allowlist`. Scripts are pre-approved when using **absolute** paths (no `cd &&`).

If exec is denied (`allowlist-miss`), approve once in chat, or run:

```bash
openclaw approvals allowlist add --agent main "/usr/bin/python3"
```

## Errors

| Situation | Action |
|-----------|--------|
| `Exec denied (allowlist-miss)` | Use absolute script path; no `cd &&` |
| Overpass timeout | Retry once; say maps lookup is temporarily unavailable |
| Zero results | Try `--radius 300` or `--focus tourist`; OSM may be sparse in rural areas |
| Walk mode silent | Check hook enabled + live location active + user moved 100 m or waited 5 min |
| Hook not enabled | `openclaw hooks enable walk-guide` and restart gateway |
