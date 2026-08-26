import { AnimeInfo, AnimeSummary, PageInfo } from "./types";

const ANILIST = "https://graphql.anilist.co";

/**
 * AniList sits behind Cloudflare and drops non-browser User-Agents
 * (learned the hard way in the desktop app) — always send Chrome UA.
 */
const HEADERS: Record<string, string> = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
  "Content-Type": "application/json",
  Accept: "application/json",
};

export async function gql<T>(
  query: string,
  variables: Record<string, unknown>,
  revalidate = 600
): Promise<T> {
  const res = await fetch(ANILIST, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify({ query, variables }),
    next: { revalidate },
  });
  if (!res.ok) {
    throw new Error(`AniList HTTP ${res.status}`);
  }
  const json = await res.json();
  if (json.errors?.length) {
    throw new Error(
      "AniList GraphQL: " +
        json.errors.map((e: { message: string }) => e.message).join("; ")
    );
  }
  return json.data as T;
}

const CARD_FIELDS = `
  id
  title { romaji english }
  coverImage { extraLarge large }
  bannerImage
  format
  seasonYear
  averageScore
  genres
`;

interface RawMedia {
  id: number;
  title: { romaji: string | null; english: string | null };
  coverImage: { extraLarge?: string; large?: string } | null;
  bannerImage?: string | null;
  format?: string | null;
  seasonYear?: number | null;
  averageScore?: number | null;
  genres?: string[] | null;
  description?: string | null;
  status?: string | null;
  duration?: number | null;
  episodes?: number | null;
  studios?: { nodes: { name: string }[] } | null;
}

function shape(m: RawMedia): AnimeSummary {
  return {
    id: String(m.id),
    title: m.title.english || m.title.romaji || String(m.id),
    romaji: m.title.romaji || undefined,
    poster: m.coverImage?.extraLarge || m.coverImage?.large || "",
    banner: m.bannerImage || undefined,
    format: m.format || undefined,
    year: m.seasonYear || undefined,
    score: m.averageScore ? m.averageScore / 10 : undefined,
    provider: "anilist",
    genres: m.genres || [],
  };
}

export async function fetchTrending(perPage = 24): Promise<AnimeSummary[]> {
  const data = await gql<{ Page: { media: RawMedia[] } }>(
    `query ($perPage: Int) {
       Page(page: 1, perPage: $perPage) {
         media(type: ANIME, sort: TRENDING_DESC, isAdult: false) {
           ${CARD_FIELDS}
         }
       }
     }`,
    { perPage },
    300
  );
  return data.Page.media.map(shape);
}

export async function fetchBrowse(opts: {
  genre?: string;
  sort?: string;
  season?: "current" | "upcoming" | "";
  page?: number;
  perPage?: number;
}): Promise<{ items: AnimeSummary[]; info: PageInfo }> {
  // AniList enum is British: FAVOURITES_DESC. Normalize aliases up front.
  const sortRaw = (opts.sort || "TRENDING_DESC").toUpperCase();
  const sort = sortRaw === "FAVORITES_DESC" ? "FAVOURITES_DESC" : sortRaw;
  const variables: Record<string, unknown> = {
    page: Math.max(1, opts.page || 1),
    perPage: Math.min(50, opts.perPage || 30),
    sort: [sort],
  };
  if (opts.genre && opts.genre.toLowerCase() !== "all") {
    variables.genre = [opts.genre];
  }
  if (opts.season === "current" || opts.season === "upcoming") {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth() + 1;
    const cycle = ["WINTER", "SPRING", "SUMMER", "FALL"] as const;
    const cur = cycle[Math.floor(((m + 1) % 12) / 3)];
    const curIdx = cycle.indexOf(cur as (typeof cycle)[number]);
    if (opts.season === "current") {
      variables.season = cur;
      variables.seasonYear = y;
    } else {
      const nxt = cycle[(curIdx + 1) % 4];
      variables.season = nxt;
      variables.seasonYear = cur === "FALL" ? y + 1 : y;
    }
  }
  const data = await gql<{
    Page: {
      pageInfo: { total: number; currentPage: number; hasNextPage: boolean };
      media: RawMedia[];
    };
  }>(
    `query ($page: Int, $perPage: Int, $genre: [String], $sort: [MediaSort],
            $season: MediaSeason, $seasonYear: Int) {
       Page(page: $page, perPage: $perPage) {
         pageInfo { total currentPage hasNextPage }
         media(type: ANIME, genre_in: $genre, sort: $sort,
               season: $season, seasonYear: $seasonYear, isAdult: false) {
           ${CARD_FIELDS}
         }
       }
     }`,
    variables,
    300
  );
  return {
    items: data.Page.media.map(shape),
    info: {
      total: data.Page.pageInfo.total,
      currentPage: data.Page.pageInfo.currentPage,
      hasNextPage: data.Page.pageInfo.hasNextPage,
    },
  };
}

export async function searchAnime(
  q: string,
  page = 1,
  perPage = 24
): Promise<{ items: AnimeSummary[]; info: PageInfo }> {
  const data = await gql<{
    Page: {
      pageInfo: { total: number; currentPage: number; hasNextPage: boolean };
      media: RawMedia[];
    };
  }>(
    `query ($search: String, $page: Int, $perPage: Int) {
       Page(page: $page, perPage: $perPage) {
         pageInfo { total currentPage hasNextPage }
         media(search: $search, type: ANIME, sort: [SEARCH_MATCH, POPULARITY_DESC],
               isAdult: false) {
           ${CARD_FIELDS}
         }
       }
     }`,
    { search: q, page, perPage },
    60
  );
  return {
    items: data.Page.media.map(shape),
    info: {
      total: data.Page.pageInfo.total,
      currentPage: data.Page.pageInfo.currentPage,
      hasNextPage: data.Page.pageInfo.hasNextPage,
    },
  };
}

export async function fetchInfo(id: string): Promise<AnimeInfo | null> {
  try {
    const data = await gql<{ Media: RawMedia }>(
      `query ($id: Int) {
         Media(id: $id, type: ANIME) {
           ${CARD_FIELDS}
           description(asHtml: false)
           status
           duration
           episodes
           studios(isMain: true) { nodes { name } }
         }
       }`,
      { id: parseInt(id, 10) },
      1800
    );
    const m = data.Media;
    if (!m) return null;
    return {
      ...shape(m),
      synopsis: (m.description || "").replace(/<[^>]+>/g, "").trim(),
      status: m.status || undefined,
      duration: m.duration || undefined,
      episodes: m.episodes ?? null,
      studios: (m.studios?.nodes || []).map((n) => n.name),
    };
  } catch {
    return null;
  }
}
