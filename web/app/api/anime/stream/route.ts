import { NextResponse } from "next/server";
import { resolveEpisode } from "@/lib/consumet";

export const dynamic = "force-dynamic";

/**
 * Resolve playable sources for an episode.
 * GET /api/anime/stream?title=...&episode=3&category=sub
 * Sources are already proxied through /api/stream?url=...
 */
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const title = (searchParams.get("title") || "").trim();
  const episode = parseInt(searchParams.get("episode") || "1", 10);
  const category = (searchParams.get("category") || "sub") as
    | "sub"
    | "dub"
    | "ar_sub";

  if (!title || !Number.isFinite(episode)) {
    return NextResponse.json(
      { ok: false, sources: [], error: "missing title/episode" },
      { status: 400 }
    );
  }

  try {
    const { episodes, sources } = await resolveEpisode(title, episode, category);
    return NextResponse.json({
      ok: sources.length > 0,
      sources,
      episodes,
      error: sources.length ? undefined : "no playable sources upstream",
    });
  } catch (e) {
    return NextResponse.json({
      ok: false,
      sources: [],
      error: String(e instanceof Error ? e.message : e),
    });
  }
}
