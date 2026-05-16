# nearby-places (OpenClaw Agent Skill)

Lists shops, restaurants, transit, and tourist/historic places near the user using **OpenStreetMap** (Overpass + Nominatim). Built for **Telegram location pins** and optional **live-location walking tours**.

- **Skill instructions:** [`SKILL.md`](./SKILL.md)
- **Optional hook (walk mode):** [`hooks/walk-guide/`](./hooks/walk-guide/)

## Requirements

- **Python 3** (stdlib only — no pip packages)
- **`curl`** (optional; scripts use `urllib`)
- **OpenClaw** (for walk-mode Telegram alerts via `openclaw message send`)

## Install (OpenClaw workspace)

```bash
cd /path/to/your/openclaw/workspace/skills
git clone https://github.com/curumim-taruma/nearby-places-skill.git nearby-places
```

Copy the walk hook into your workspace (optional, for live-location tours):

```bash
cp -r /path/to/nearby-places/hooks/walk-guide /path/to/workspace/hooks/walk-guide
openclaw hooks enable walk-guide
# restart gateway
```

Add exec allowlist entries for `python3` and the absolute script paths (see `SKILL.md`).

## Quick test

```bash
python3 scripts/nearby.py --lat -22.722279 --lon -45.561974 --radius 150
python3 scripts/nearby.py --lat -22.722279 --lon -45.561974 --radius 150 --focus tourist
```

## Paths (portable)

| Variable | Purpose |
|----------|---------|
| `OPENCLAW_WORKSPACE` | Root for walk-mode state (`location_walk/sessions/`). Default: parent of `skills/` when installed under OpenClaw, else the skill directory. |
| `OVERPASS_URL` | Optional single Overpass API endpoint (default: tries several public mirrors). |
| `NEARBY_PLACES_USER_AGENT` | Optional User-Agent for OSM API requests. |

Run scripts from the skill root (`cd` to the folder containing `SKILL.md`) or use absolute paths (required for OpenClaw exec allowlist).

## Repository

https://github.com/curumim-taruma/nearby-places-skill

## License

MIT — see [LICENSE](./LICENSE).
