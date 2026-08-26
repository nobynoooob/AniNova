import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export const dynamic = "force-dynamic";

/**
 * Emoji reaction counters, persisted to .data/reactions.json.
 * Keys: `${animeId}:${episode}` or `anime:${animeId}`.
 */
const EMOJIS = ["fire", "heart", "laugh", "shock", "thumbs"] as const;
type Emoji = (typeof EMOJIS)[number];

const DATA_DIR = path.join(process.cwd(), ".data");
const FILE = path.join(DATA_DIR, "reactions.json");

type Store = Record<string, Partial<Record<Emoji, number>>>;
let cache: Store | null = null;

async function load(): Promise<Store> {
  if (cache) return cache;
  try {
    cache = JSON.parse(await fs.readFile(FILE, "utf8")) as Store;
  } catch {
    cache = {};
  }
  return cache;
}

async function save(store: Store): Promise<void> {
  cache = store;
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(FILE, JSON.stringify(store), "utf8");
}

function keyOf(animeId: string, episode?: number | null): string {
  return episode != null && Number.isFinite(episode)
    ? `${animeId}:${episode}`
    : `anime:${animeId}`;
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const animeId = searchParams.get("animeId") || "";
  const epRaw = searchParams.get("episode");
  const episode = epRaw != null ? parseInt(epRaw, 10) : null;
  if (!animeId) {
    return NextResponse.json({ error: "missing animeId" }, { status: 400 });
  }
  const store = await load();
  const counts = store[keyOf(animeId, episode)] || {};
  const out: Record<string, number> = {};
  for (const e of EMOJIS) out[e] = counts[e] || 0;
  return NextResponse.json({ ok: true, counts: out });
}

export async function POST(req: Request) {
  let body: { animeId?: string; episode?: number; emoji?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad json" }, { status: 400 });
  }
  const animeId = String(body.animeId || "");
  const emoji = String(body.emoji || "") as Emoji;
  const episode =
    body.episode != null && Number.isFinite(body.episode)
      ? Number(body.episode)
      : null;
  if (!animeId || !EMOJIS.includes(emoji)) {
    return NextResponse.json({ error: "bad payload" }, { status: 400 });
  }
  const store = await load();
  const key = keyOf(animeId, episode);
  const counts = store[key] || {};
  counts[emoji] = (counts[emoji] || 0) + 1;
  store[key] = counts;
  await save(store);
  const out: Record<string, number> = {};
  for (const e of EMOJIS) out[e] = store[key][e] || 0;
  return NextResponse.json({ ok: true, counts: out });
}
