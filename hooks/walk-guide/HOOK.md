---
name: walk-guide
description: "Live walking-tour alerts for tourist/historic POIs when Telegram live location updates arrive."
metadata:
  openclaw:
    emoji: "🚶"
    events:
      - "message:received"
    requires:
      bins: ["python3", "openclaw"]
---

# Walk Guide Hook

Handles **walk mode** without invoking the LLM on every live-location ping.

On each inbound Telegram message:

1. Parses coordinates from location shares (`📍` / `🛰 Live location: lat, lon`).
2. Runs `skills/nearby-places/scripts/walk_guide.py inbound`.
3. Sends Telegram alerts for **new** tourist/historic places when thresholds are met.

## Install

Copy this folder to your OpenClaw workspace:

```bash
cp -r hooks/walk-guide /path/to/workspace/hooks/walk-guide
openclaw hooks enable walk-guide
```

Restart the gateway after enabling.

Ensure the **nearby-places** skill is installed at `workspace/skills/nearby-places/` (or set `NEARBY_PLACES_WALK_SCRIPT` to the absolute path of `walk_guide.py`).
