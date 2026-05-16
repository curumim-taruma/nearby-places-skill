#!/usr/bin/env python3
"""
Walking tour mode: periodic tourist/historic POI alerts while live location is shared.

State: workspace/location_walk/sessions/<chat_id>.json
Sends Telegram via: openclaw message send --channel telegram -t <chat_id> -m "..."
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from osm_core import fetch_nearby, haversine_m, reverse_geocode

SKILL_DIR = Path(__file__).resolve().parent.parent


def workspace_root() -> Path:
    """OpenClaw workspace or standalone skill directory for walk-session state."""
    env = (os.environ.get("OPENCLAW_WORKSPACE") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if SKILL_DIR.parent.name == "skills":
        return SKILL_DIR.parent.parent.resolve()
    return SKILL_DIR.resolve()


STATE_ROOT = workspace_root() / "location_walk" / "sessions"

DEFAULT_MIN_INTERVAL_SEC = 300
DEFAULT_MIN_DISTANCE_M = 100
DEFAULT_RADIUS_M = 150
DEFAULT_MAX_PER_ALERT = 8
MAX_ANNOUNCED = 400

START_RE = re.compile(
    r"(?i)\b("
    r"/walk|walk\s*guide|modo\s*passeio|guia\s*(tur[ií]stico|de\s*passeio)|"
    r"start\s*walk|turismo\s*ao\s*vivo|passeio\s*guiado"
    r")\b"
)
STOP_RE = re.compile(
    r"(?i)\b(/stop-walk|stop\s*walk|parar\s*passeio|fim\s*do\s*passeio|encerrar\s*passeio)\b"
)
COORD_RE = re.compile(r"(-?\d{1,3}\.\d{4,}),\s*(-?\d{1,3}\.\d{4,})")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_path(chat_id: str) -> Path:
    safe = re.sub(r"[^\w.-]+", "_", chat_id)
    return STATE_ROOT / f"{safe}.json"


def load_session(chat_id: str) -> dict[str, Any] | None:
    path = session_path(chat_id)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_session(chat_id: str, data: dict[str, Any]) -> None:
    path = session_path(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def delete_session(chat_id: str) -> None:
    path = session_path(chat_id)
    if path.exists():
        path.unlink()


def default_config() -> dict[str, Any]:
    return {
        "min_interval_sec": DEFAULT_MIN_INTERVAL_SEC,
        "min_distance_m": DEFAULT_MIN_DISTANCE_M,
        "radius_m": DEFAULT_RADIUS_M,
        "max_per_alert": DEFAULT_MAX_PER_ALERT,
    }


def send_telegram(chat_id: str, message: str) -> None:
    text = message.strip()
    if not text:
        return
    cmd = [
        "openclaw",
        "message",
        "send",
        "--channel",
        "telegram",
        "--target",
        chat_id,
        "--message",
        text[:3900],
    ]
    subprocess.run(cmd, check=True, timeout=60, capture_output=True, text=True)


def parse_coords(text: str) -> tuple[float, float] | None:
    match = COORD_RE.search(text or "")
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def extract_chat_id(session_key: str | None, metadata: dict[str, Any] | None) -> str | None:
    meta = metadata or {}
    sender = str(meta.get("senderId") or "").strip()
    if sender.isdigit():
        return sender
    if session_key:
        parts = session_key.split(":")
        if parts and parts[-1].isdigit():
            return parts[-1]
    conv = str(meta.get("conversationId") or "").strip()
    if conv.isdigit():
        return conv
    return None


def should_alert(session: dict[str, Any], lat: float, lon: float, force: bool) -> bool:
    if force:
        return True
    cfg = session.get("config") or {}
    min_dist = float(cfg.get("min_distance_m", DEFAULT_MIN_DISTANCE_M))
    min_interval = float(cfg.get("min_interval_sec", DEFAULT_MIN_INTERVAL_SEC))

    last_lat = session.get("last_lat")
    last_lon = session.get("last_lon")
    last_alert_at = session.get("last_alert_at")

    moved_enough = True
    if isinstance(last_lat, (int, float)) and isinstance(last_lon, (int, float)):
        moved_enough = haversine_m(last_lat, last_lon, lat, lon) >= min_dist

    waited_enough = True
    if isinstance(last_alert_at, str):
        try:
            prev = datetime.fromisoformat(last_alert_at.replace("Z", "+00:00"))
            waited_enough = (datetime.now(timezone.utc) - prev).total_seconds() >= min_interval
        except ValueError:
            waited_enough = True

    return moved_enough or waited_enough


def format_walk_alert(
    lat: float,
    lon: float,
    radius_m: int,
    places: list[dict[str, Any]],
    address: str | None,
) -> str:
    lines = [f"🚶 **Perto de você** (~{radius_m} m)"]
    if address:
        short = address.split(",")[0:2]
        lines.append("_" + ", ".join(short).strip() + "_")
    lines.append("")
    for p in places:
        emoji = p.get("emoji") or "📍"
        lines.append(f"{emoji} {p['name']} — **{p['distance_m']} m**")
    lines.append("")
    lines.append(f"_OpenStreetMap · {len(places)} lugar(es) novo(s)_")
    return "\n".join(lines)


def cmd_start(chat_id: str, lat: float | None, lon: float | None, **cfg_overrides: Any) -> str:
    config = default_config()
    config.update({k: v for k, v in cfg_overrides.items() if v is not None})

    session = {
        "active": True,
        "chat_id": chat_id,
        "channel": "telegram",
        "started_at": utc_now_iso(),
        "last_lat": lat,
        "last_lon": lon,
        "last_alert_at": None,
        "announced": [],
        "config": config,
    }
    save_session(chat_id, session)

    if lat is None or lon is None:
        return (
            "🚶 **Modo passeio ativado.**\n\n"
            "Compartilhe sua **localização ao vivo** no Telegram (anexo → Localização → "
            "Compartilhar localização em tempo real).\n\n"
            f"Vou avisar a cada **{int(config['min_distance_m'])} m** ou **{int(config['min_interval_sec']) // 60} min** "
            "sobre pontos **turísticos e históricos** por perto.\n\n"
            "Para parar: `parar passeio` ou `/stop-walk`."
        )

    msg = update_position(chat_id, lat, lon, force=True)
    prefix = (
        "🚶 **Modo passeio ativado.** Acompanhando sua localização ao vivo.\n"
        f"Alertas: a cada **{int(config['min_distance_m'])} m** ou **{int(config['min_interval_sec']) // 60} min**.\n"
        "Para parar: `parar passeio`.\n\n"
    )
    return prefix + (msg or "_Nenhum ponto turístico novo no momento — continue caminhando._")


def cmd_stop(chat_id: str) -> str:
    existed = load_session(chat_id) is not None
    delete_session(chat_id)
    if existed:
        return "🛑 Modo passeio encerrado. Até a próxima!"
    return "Modo passeio não estava ativo."


def update_position(chat_id: str, lat: float, lon: float, *, force: bool = False) -> str | None:
    session = load_session(chat_id)
    if not session or not session.get("active"):
        return None

    if not should_alert(session, lat, lon, force):
        session["last_lat"] = lat
        session["last_lon"] = lon
        save_session(chat_id, session)
        return None

    cfg = session.get("config") or default_config()
    radius_m = int(cfg.get("radius_m", DEFAULT_RADIUS_M))
    max_per = int(cfg.get("max_per_alert", DEFAULT_MAX_PER_ALERT))

    try:
        places = fetch_nearby(lat, lon, radius_m, focus="tourist", max_results=40)
    except RuntimeError as exc:
        return f"⚠️ Não consegui consultar o mapa: {exc}"

    announced = set(session.get("announced") or [])
    new_places = [p for p in places if p["osm"] not in announced]
    if not new_places:
        session["last_lat"] = lat
        session["last_lon"] = lon
        session["last_alert_at"] = utc_now_iso()
        save_session(chat_id, session)
        return None

    batch = new_places[:max_per]
    address = reverse_geocode(lat, lon)
    message = format_walk_alert(lat, lon, radius_m, batch, address)

    for p in batch:
        announced.add(p["osm"])
    announced_list = list(announced)
    if len(announced_list) > MAX_ANNOUNCED:
        announced_list = announced_list[-MAX_ANNOUNCED:]

    session["announced"] = announced_list
    session["last_lat"] = lat
    session["last_lon"] = lon
    session["last_alert_at"] = utc_now_iso()
    save_session(chat_id, session)

    try:
        send_telegram(chat_id, message)
    except subprocess.CalledProcessError as exc:
        return f"⚠️ Falha ao enviar no Telegram: {exc.stderr or exc}"

    return message


def handle_inbound(
    *,
    chat_id: str,
    content: str,
    lat: float | None = None,
    lon: float | None = None,
    notify: bool = True,
) -> str | None:
    """Process one inbound message; returns user-visible text if any."""
    text = (content or "").strip()

    if STOP_RE.search(text):
        return cmd_stop(chat_id)

    coords = (lat, lon) if lat is not None and lon is not None else parse_coords(text)
    if START_RE.search(text):
        return cmd_start(chat_id, *(coords or (None, None)))

    session = load_session(chat_id)
    if not session or not session.get("active"):
        return None

    if coords:
        c_lat, c_lon = coords
        result = update_position(chat_id, c_lat, c_lon, force=False)
        if result and notify:
            return None  # already sent via Telegram
        return None

    return None


def cmd_status(chat_id: str) -> str:
    session = load_session(chat_id)
    if not session or not session.get("active"):
        return "Modo passeio: **inativo**."
    cfg = session.get("config") or {}
    announced = len(session.get("announced") or [])
    return (
        "Modo passeio: **ativo**\n"
        f"- Raio: {cfg.get('radius_m', DEFAULT_RADIUS_M)} m\n"
        f"- Intervalo mín.: {cfg.get('min_interval_sec', DEFAULT_MIN_INTERVAL_SEC)} s\n"
        f"- Distância mín.: {cfg.get('min_distance_m', DEFAULT_MIN_DISTANCE_M)} m\n"
        f"- Lugares já avisados: {announced}\n"
        f"- Última posição: {session.get('last_lat')}, {session.get('last_lon')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Walking tour live-location guide.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--chat-id", required=True)
    p_start.add_argument("--lat", type=float)
    p_start.add_argument("--lon", type=float)
    p_start.add_argument("--min-interval", type=int, dest="min_interval_sec")
    p_start.add_argument("--min-distance", type=int, dest="min_distance_m")
    p_start.add_argument("--radius", type=int, dest="radius_m")
    p_start.add_argument("--no-notify", action="store_true")

    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--chat-id", required=True)

    p_update = sub.add_parser("update")
    p_update.add_argument("--chat-id", required=True)
    p_update.add_argument("--lat", type=float, required=True)
    p_update.add_argument("--lon", type=float, required=True)
    p_update.add_argument("--force", action="store_true")
    p_update.add_argument("--content", default="")
    p_update.add_argument("--session-key", default="")

    p_status = sub.add_parser("status")
    p_status.add_argument("--chat-id", required=True)

    p_inbound = sub.add_parser("inbound")
    p_inbound.add_argument("--chat-id", required=True)
    p_inbound.add_argument("--content", default="")
    p_inbound.add_argument("--lat", type=float)
    p_inbound.add_argument("--lon", type=float)

    args = parser.parse_args()

    if args.command == "start":
        msg = cmd_start(
            args.chat_id,
            args.lat,
            args.lon,
            min_interval_sec=args.min_interval_sec,
            min_distance_m=args.min_distance_m,
            radius_m=args.radius_m,
        )
        if msg and not args.no_notify:
            try:
                send_telegram(args.chat_id, msg)
            except subprocess.CalledProcessError as exc:
                print(exc.stderr or exc, file=sys.stderr)
                return 1
        elif msg:
            print(msg)
        return 0

    if args.command == "stop":
        msg = cmd_stop(args.chat_id)
        try:
            send_telegram(args.chat_id, msg)
        except subprocess.CalledProcessError:
            print(msg)
        return 0

    if args.command == "update":
        if START_RE.search(args.content or ""):
            print(cmd_start(args.chat_id, args.lat, args.lon))
            return 0
        if STOP_RE.search(args.content or ""):
            print(cmd_stop(args.chat_id))
            return 0
        result = update_position(args.chat_id, args.lat, args.lon, force=args.force)
        if result:
            print(result)
        return 0

    if args.command == "status":
        print(cmd_status(args.chat_id))
        return 0

    if args.command == "inbound":
        msg = handle_inbound(
            chat_id=args.chat_id,
            content=args.content,
            lat=args.lat,
            lon=args.lon,
        )
        if msg:
            try:
                send_telegram(args.chat_id, msg)
            except subprocess.CalledProcessError as exc:
                print(exc.stderr or exc, file=sys.stderr)
                return 1
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
