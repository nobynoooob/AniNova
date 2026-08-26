import { EpisodeEntry } from "./types";

/**
 * AniZip mapping engine — free, keyless, no search step needed.
 * https://api.ani.zip/mappings?anilist_id={id}
 *
 * Provides canonical episode metadata (counts, titles, images) keyed by
 * episode number. Specials use non-numeric keys ("S1", "SP") and are
 * separated from the main list.
 */

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36";

interface AniZipEpisode {
  episode?: string;
  episodeNumber?: number;
  title?: { en?: string; ja?: string } | string | null;
  image?: string;
}

interface AniZipPayload {
  episodeCount?: number;
  episodes?: Record<string, AniZipEpisode> | null;
  mappings?: Record<string, unknown>;
}

export interface AniZipResult {
  episodes: EpisodeEntry[];      // canonical numbered episodes
  titles: Record<number, string>; // ep number -> title
  images: Record<number, string>; // ep number -> thumbnail
  total: number;
}

// 5-minute server cache; mappings are static for finished shows and only
// grow for airing ones — plenty for a browsing session.
let cache: { at: number; data: AniZipResult } | null = null;
const CACHE_MS = 5 * 60 * 1000;

export async function anizipEpisodes(anilistId: string): Promise<AniZipResult | null> {
  if (cache && Date.now() - cache.at < CACHE_MS) return cache.data;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 10000);
    const res = await fetch(
      `https://api.ani.zip/mappings?anilist_id=${encodeURIComponent(anilistId)}`,
      { headers: { "User-Agent": UA }, signal: ctrl.signal,
        next: { revalidate: 300 } }
    );
    clearTimeout(t);
    if (!res.ok) return null;
    const data = (await res.json()) as AniZipPayload;
    const eps = data.episodes || {};
    const episodes: EpisodeEntry[] = [];
    const titles: Record<number, string> = {};
    const images: Record<number, string> = {};
    for (const [key, ep] of Object.entries(eps)) {
      const num = Number(key);
      if (!Number.isFinite(num) || num <= 0) continue; // skip "S1"/"SP" specials
      episodes.push({ num, id: String(num) });
      const t =
        typeof ep.title === "string"
          ? ep.title
          : ep.title?.en || undefined;
      if (t) titles[num] = t;
      if (ep.image) images[num] = ep.image;
    }
    episodes.sort((a, b) => a.num - b.num);
    const out: AniZipResult = {
      episodes,
      titles,
      images,
      total: data.episodeCount || episodes.length,
    };
    cache = { at: Date.now(), data: out };
    return out;
  } catch {
    return null;
  }
}
