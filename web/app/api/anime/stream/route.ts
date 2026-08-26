import { NextResponse } from "next/server";
import { resolveSources } from "@/lib/streams";

export const dynamic = "force-dynamic";

/**
 * Resolve playable sources for an episode via the direct AllAnime resolver.
 * GET /api/anime/stream?title=...&episode=3&showId=<optional allanime id>
 * Sources are already proxied through /api/stream?url=...
 */
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const title = (searchParams.get("title") || "").trim();
  const episode = parseInt(searchParams.get("episode") || "1", 10);
  const showId = searchParams.get("showId") || undefined;
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
    const sources = await resolveSources(title, episode, showId, category);
    return NextResponse.json({
      ok: sources.length > 0,
      sources,
      error: sources.length ? undefined : "no playable sources upstream",
    });
  } catch (e) {
    return NextResponse.json({
      ok: false,
      sources: [],
      error: String(e instanceof Error ? `${e.name}: ${e.message}` : e),
    });
  }
}
