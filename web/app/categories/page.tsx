"use client";

import { AnimeCard, CardGridSkeleton } from "@/components/AnimeCard";
import { GENRES, SORTS } from "@/lib/types";
import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";
import { AnimeSummary } from "@/lib/types";

export default function CategoriesPage() {
  const [genre, setGenre] = useState("");
  const [sort, setSort] = useState<string>("TRENDING_DESC");
  const [season, setSeason] = useState<"" | "current" | "upcoming">("");
  const [items, setItems] = useState<AnimeSummary[]>([]);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef(true);

  async function load(reset: boolean) {
    if (loading) return;
    setLoading(true);
    setError(null);
    const p = reset ? 1 : page + 1;
    try {
      const params = new URLSearchParams({ sort, page: String(p) });
      if (genre) params.set("genre", genre);
      if (season) params.set("season", season);
      const res = await fetch(`/api/anime/browse?${params}`);
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "failed");
      setItems((prev) => (reset ? data.items : [...prev, ...data.items]));
      setHasNext(!!data.info?.hasNextPage);
      setPage(p);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
      first.current = false;
    }
  }

  useEffect(() => {
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genre, sort, season]);

  const pickGenre = (g: string) => {
    if (g === genre) return;
    setGenre(g);
    // Relevance defaults: genre => Top Rated, All => Trending
    setSort(g ? "SCORE_DESC" : "TRENDING_DESC");
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="mb-5 flex items-center gap-3">
        <span className="h-5 w-1.5 rounded-full bg-gradient-to-b from-sunrise to-sunrise-soft shadow-glow-sm" />
        <h1 className="text-lg font-extrabold tracking-wide">Categories</h1>
      </div>

      {/* Genre chips */}
      <div className="mb-4 flex flex-wrap gap-2">
        <button
          onClick={() => pickGenre("")}
          className={`chip ${genre === "" ? "chip-active" : ""}`}
        >
          All
        </button>
        {GENRES.map((g) => (
          <button
            key={g}
            onClick={() => pickGenre(g)}
            className={`chip ${genre === g ? "chip-active" : ""}`}
          >
            {g}
          </button>
        ))}
      </div>

      {/* Controls */}
      <div className="mb-6 flex flex-wrap gap-3">
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="rounded-2xl border border-line bg-card px-4 py-2.5 text-sm font-semibold outline-none focus:border-sunrise"
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <select
          value={season}
          onChange={(e) => setSeason(e.target.value as "" | "current" | "upcoming")}
          className="rounded-2xl border border-line bg-card px-4 py-2.5 text-sm font-semibold outline-none focus:border-sunrise"
        >
          <option value="">All Seasons</option>
          <option value="current">This Season</option>
          <option value="upcoming">Upcoming</option>
        </select>
      </div>

      {/* Results */}
      {loading && items.length === 0 && <CardGridSkeleton n={12} />}
      {error && (
        <div className="browse-error flex flex-col items-center gap-4 py-16 text-ink-sec">
          <div>Couldn&apos;t load this category — {error}</div>
          <button onClick={() => load(true)} className="btn-sunrise">
            <RotateCcw size={16} /> Retry
          </button>
        </div>
      )}
      {!error && !loading && items.length === 0 && (
        <div className="py-16 text-center text-ink-sec">
          No results. Try another genre.
        </div>
      )}
      {items.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
          {items.map((a, i) => (
            <AnimeCard key={`${a.id}-${i}`} anime={a} priority={i < 6} />
          ))}
        </div>
      )}

      {/* Load more */}
      <div className="flex justify-center py-8">
        {hasNext && (
          <button
            onClick={() => load(false)}
            disabled={loading}
            className="btn-sunrise min-w-[200px]"
          >
            {loading ? "Loading…" : "Load More"}
          </button>
        )}
      </div>
    </div>
  );
}
