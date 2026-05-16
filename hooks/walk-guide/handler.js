/**
 * Walk-guide hook: tourist/historic POI alerts during Telegram live location walks.
 * Fires on message:received — uses walk_guide.py (no LLM per location ping).
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE_DIR = process.env.OPENCLAW_WORKSPACE
  ? path.resolve(process.env.OPENCLAW_WORKSPACE)
  : path.resolve(__dirname, "../..");

function resolveWalkScript() {
  if (process.env.NEARBY_PLACES_WALK_SCRIPT) {
    return path.resolve(process.env.NEARBY_PLACES_WALK_SCRIPT);
  }
  const candidates = [
    path.join(WORKSPACE_DIR, "skills/nearby-places/scripts/walk_guide.py"),
    path.join(WORKSPACE_DIR, "nearby-places/scripts/walk_guide.py"),
    path.resolve(__dirname, "../../scripts/walk_guide.py"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return candidates[0];
}

const WALK_SCRIPT = resolveWalkScript();
const COORD_RE = /(-?\d{1,3}\.\d{4,}),\s*(-?\d{1,3}\.\d{4,})/;

function extractChatId(event) {
  const ctx = event?.context;
  if (!ctx || typeof ctx !== "object") return null;
  const meta = ctx.metadata;
  if (meta && typeof meta === "object") {
    const senderId = String(meta.senderId ?? "").trim();
    if (/^\d+$/.test(senderId)) return senderId;
    const conv = String(meta.conversationId ?? "").trim();
    if (/^\d+$/.test(conv)) return conv;
  }
  const sessionKey = String(event.sessionKey ?? "");
  const parts = sessionKey.split(":");
  const last = parts[parts.length - 1];
  if (/^\d+$/.test(last)) return last;
  return null;
}

function parseCoords(content) {
  const text = String(content ?? "");
  const match = COORD_RE.exec(text);
  if (!match) return null;
  return { lat: match[1], lon: match[2] };
}

function runWalkGuide(args) {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [WALK_SCRIPT, ...args], {
      cwd: WORKSPACE_DIR,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || stdout.trim() || `exit ${code}`));
        return;
      }
      resolve(stdout.trim());
    });
  });
}

const handler = async (event) => {
  if (event?.type !== "message" || event?.action !== "received") return;

  const channelId = String(event?.context?.channelId ?? "").toLowerCase();
  if (channelId && channelId !== "telegram") return;

  const chatId = extractChatId(event);
  if (!chatId) return;

  const content = String(event?.context?.content ?? "");
  const coords = parseCoords(content);

  const args = ["inbound", "--chat-id", chatId, "--content", content];
  if (coords) {
    args.push("--lat", coords.lat, "--lon", coords.lon);
  }

  try {
    await runWalkGuide(args);
  } catch (err) {
    console.error(`[walk-guide] ${err?.message ?? err}`);
  }
};

export default handler;
