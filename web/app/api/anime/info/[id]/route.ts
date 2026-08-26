import { NextResponse } from "next/server";
import { fetchInfo } from "@/lib/anilist";
import { resolveEpisodes } from "@/lib/streams";
import { EpisodeEntry } from "@/lib/types";

export const revalidate = 300;

export async function GET(
  _req: Request,
  { params }: { params: { id: string } }
) {
  const info = await fetchInfo(params.id);
  if (!info) {
    return NextResponse.json(
      { ok: false, error: "not found", info: null, episodes: [] },
      { status: 404 }
    );
  }
  // Episode list: AllAnime (primary) -> AniZip mappings (fallback).
  // Best-effort so metadata still renders when both miss.
  let episodes: EpisodeEntry[] = [];
  let titles: Record<number, string> = {};
  let episodeSource = "none";
  let showId: string | undefined;
  let episodesError: string | undefined;
  try {
    const res = await resolveEpisodes(info.title, info.id);
    episodes = res.episodes;
    titles = res.titles;
    episodeSource = res.episodeSource;
    showId = res.showId;
    if (!episodes.length) episodesError = "no episode data from providers";
  } catch (e) {
    episodesError = String(e instanceof Error ? e.message : e);
  }
  return NextResponse.json({
    ok: true,
    info,
    episodes,
    titles,
    episodeSource,
    showId,
    episodesError,
  });
}
