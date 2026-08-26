"use client";

import { AnimeCard, CardGridSkeleton } from "@/components/AnimeCard";
import { AnimeSummary } from "@/lib/types";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function Results() {
  const params = useSearchParams();
  const q = params.get("q") || "";
  const [items, setItems] = useState<AnimeSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!q) return;
    setLoading(true);
    setError(null);
    fetch(`/api/anime/search?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) throw new Error(d.error || "search failed");
        setItems(d.items);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [q]);

  return (
    <>
      {loading && <CardGridSkeleton n={12} />}
      {error && <div className="py-16 text-center text-ink-sec">Search failed — {error}</div>}
      {!loading && !error && !items.length && q && (
        <div className="py-16 text-center text-ink-sec">No results for “{q}”.</div>
      )}
      {items.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
          {items.map((a, i) => (
            <AnimeCard key={a.id} anime={a} priority={i < 6} />
          ))}
        </div>
      )}
    </>
  );
}

export default function SearchPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="mb-5 flex items-center gap-3">
        <span className="h-5 w-1.5 rounded-full bg-gradient-to-b from-sunrise to-sunrise-soft shadow-glow-sm" />
        <h1 className="text-lg font-extrabold tracking-wide">Search Results</h1>
      </div>
      <Suspense fallback={<CardGridSkeleton n={12} />}>
        <Results />
      </Suspense>
    </div>
  );
}
