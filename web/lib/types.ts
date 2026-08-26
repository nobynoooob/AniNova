export interface AnimeSummary {
  id: string;
  title: string;
  romaji?: string;
  poster: string;
  banner?: string;
  format?: string;
  year?: number;
  score?: number;
  provider: string;
  genres?: string[];
}

export interface AnimeInfo extends AnimeSummary {
  synopsis?: string;
  status?: string;
  duration?: number;
  episodes?: number | null;
  studios?: string[];
  trailersite?: string;
}

export interface EpisodeEntry {
  num: number;
  id: string;
  title?: string;
}

export interface SubtitleTrack {
  url: string;          // proxied through /api/stream
  lang: string;
  label?: string;
}

export interface StreamSource {
  server: string;
  url: string;          // proxied through /api/stream
  raw?: string;         // upstream url (server-side only)
  quality?: string;
  subtitles?: SubtitleTrack[];
}

export interface WatchPayload {
  ok: boolean;
  sources: StreamSource[];
  headers?: Record<string, string>;
  error?: string;
}

export interface PageInfo {
  total: number;
  currentPage: number;
  hasNextPage: boolean;
}

export type SortKey =
  | "TRENDING_DESC"
  | "POPULARITY_DESC"
  | "SCORE_DESC"
  | "FAVOURITES_DESC";

export const GENRES = [
  "Action",
  "Adventure",
  "Comedy",
  "Drama",
  "Fantasy",
  "Horror",
  "Mystery",
  "Romance",
  "Sci-Fi",
  "Slice of Life",
] as const;

export const SORTS: { key: SortKey; label: string }[] = [
  { key: "TRENDING_DESC", label: "Trending Now" },
  { key: "POPULARITY_DESC", label: "Most Popular" },
  { key: "SCORE_DESC", label: "Top Rated" },
  { key: "FAVOURITES_DESC", label: "Favorites" },
];
