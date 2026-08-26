import { NextResponse } from "next/server";
import { fetchInfo } from "@/lib/anilist";
import { consumetEpisodes, consumetSearch } from "@/lib/consumet";

export const revalidate = 600;

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
  // Episode list is upstream-dependent; best-effort so metadata still renders.
  let episodes: { num: number; id: string; title?: string }[] = [];
  let episodesError: string | undefined;
  try {
    const found = await consumetSearch(info.title);
    if (found) {
      episodes = await consumetEpisodes(found.base, found.provider, found.animeId);
    } else {
      episodesError = "no provider instance reachable";
    }
  } catch (e) {
    episodesError = String(e instanceof Error ? e.message : e);
  }
  return NextResponse.json({
    ok: true,
    info,
    episodes,
    episodesError,
  });
}
