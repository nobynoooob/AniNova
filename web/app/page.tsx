import { CardGrid, CardGridSkeleton } from "@/components/AnimeCard";
import { Suspense } from "react";
import { fetchTrending } from "@/lib/anilist";

export const revalidate = 300;

async function TrendingRow() {
  const items = await fetchTrending(18);
  return <CardGrid items={items} priorityCount={6} />;
}

function SectionHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-5 flex items-center gap-3">
      <span className="h-5 w-1.5 rounded-full bg-gradient-to-b from-sunrise to-sunrise-soft shadow-glow-sm" />
      <h2 className="text-lg font-extrabold tracking-wide">{title}</h2>
      {hint && <span className="text-xs font-semibold text-ink-mute">{hint}</span>}
    </div>
  );
}

export default function HomePage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      {/* Hero banner */}
      <section className="relative mb-10 overflow-hidden rounded-3xl border border-line/70">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{
            backgroundImage:
              "linear-gradient(100deg, rgba(13,13,17,.96) 20%, rgba(13,13,17,.55) 60%, rgba(13,13,17,.25)), url('https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx16498-6EEdUmKa5FP2.jpg')",
          }}
        />
        <div className="relative z-10 max-w-2xl px-6 py-16 sm:px-10 sm:py-20">
          <span className="chip chip-active !text-[11px]">FEATURED · TV</span>
          <h1 className="mt-4 text-3xl font-extrabold leading-tight sm:text-5xl">
            Stream every season in the{" "}
            <span className="sunrise-text">Sunrise</span> glow.
          </h1>
          <p className="mt-4 max-w-lg text-sm leading-6 text-ink-sec sm:text-base">
            AniNova brings trending discovery, category browsing and a
            full-featured HLS player with server fallback — desktop and mobile.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <a href="/categories" className="btn-sunrise">
              Browse Categories
            </a>
            <a href="/top" className="btn-ghost">
              Top Anime
            </a>
          </div>
        </div>
      </section>

      {/* Trending */}
      <section>
        <SectionHead title="Trending Now" hint="updated hourly" />
        <Suspense fallback={<CardGridSkeleton n={12} />}>
          <TrendingRow />
        </Suspense>
      </section>
    </div>
  );
}
