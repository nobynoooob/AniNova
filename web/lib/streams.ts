import { EpisodeEntry, StreamSource } from "./types";
import { allanimeEpisodes, allanimeSearch, allanimeSources } from "./allanime";
import { anizipEpisodes } from "./anizip";
import { pythonBridgeAvailable, pythonResolve } from "./pythonBridge";

/**
 * Stream resolution pipeline (Consumet removed):
 *   1. AllAnime direct resolver (crypto handshake, no third-party API)
 *      -> episodes + playable sources
 *   2. AniZip mappings -> canonical episode metadata fallback
 *
 * Both layers are self-contained; failures surface structured errors.
 */

export interface Resolution {
  episodes: EpisodeEntry[];
  titles: Record<number, string>;
  sources: StreamSource[];
  episodeSource: "allanime" | "anizip";
  showId?: string;
}

export async function resolveEpisodes(
  title: string,
  anilistId?: string
): Promise<Resolution> {
  // Primary: AllAnime (also the streaming provider, so its episode ids are
  // the ones playback needs).
  try {
    const shows = await allanimeSearch(title);
    const best =
      shows.find(
        (s) => s.name.toLowerCase() === title.toLowerCase()
      ) || shows[0];
    if (best) {
      const episodes = await allanimeEpisodes(best.id);
      if (episodes.length) {
        return {
          episodes,
          titles: {},
          sources: [],
          episodeSource: "allanime",
          showId: best.id,
        };
      }
    }
  } catch {
    // fall through to AniZip
  }
  // Fallback: AniZip canonical episode metadata
  if (anilistId) {
    const zip = await anizipEpisodes(anilistId);
    if (zip?.episodes.length) {
      return {
        episodes: zip.episodes,
        titles: zip.titles,
        sources: [],
        episodeSource: "anizip",
      };
    }
  }
  return { episodes: [], titles: {}, sources: [], episodeSource: "anizip" };
}

const errors: string[] = [];

export async function resolveSources(
  title: string,
  episode: number,
  showId?: string,
  category: "sub" | "dub" | "ar_sub" = "sub"
): Promise<StreamSource[]> {
  errors.length = 0;
  // 1) Python bridge -> desktop ProviderManager (Miruro chain) or, for
  //    AR SUB, the ani-cli-ar Arabic pipeline (WitAnime-style catalog with
  //    baked-in Arabic subtitles). Strongest extractor; available in
  //    self-hosted/dev layouts.
  if (pythonBridgeAvailable()) {
    try {
      return await pythonResolve(title, episode, category);
    } catch (e) {
      // AR SUB has no other resolver — surface immediately for the Retry UI.
      if (category === "ar_sub") throw e;
      errors.push(`py: ${e instanceof Error ? e.message : e}`);
    }
  }
  // 2) In-process AllAnime crypto resolver (English only; works whenever
  //    the upstream client build-id/mask pair is current).
  if (category === "ar_sub") {
    throw new Error(
      errors.join(" | ") || "arabic resolver unavailable"
    );
  }
  try {
    let id = showId;
    if (!id) {
      const shows = await allanimeSearch(title);
      const best =
        shows.find((s) => s.name.toLowerCase() === title.toLowerCase()) ||
        shows[0];
      if (!best) throw new Error("title not found on any provider");
      id = best.id;
    }
    const sources = await allanimeSources(id, String(episode));
    if (sources.length) return sources;
    errors.push("allanime: 0 sources");
  } catch (e) {
    errors.push(`allanime: ${e instanceof Error ? e.message : e}`);
  }
  throw new Error(
    errors.length ? errors.join(" | ") : "all resolvers failed"
  );
}
