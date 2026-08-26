import { CardGridSkeleton } from "@/components/AnimeCard";
import { Suspense } from "react";

/** Simple discovery stubs sharing the trending feed, per nav spec. */
async function Feed({ sort }: { sort: string }) {
  const { fetchBrowse } = await import("@/lib/anilist");
  const { items } = await fetchBrowse({ sort, perPage: 30 });
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
      {items.map((a, i) => (
        <a key={a.id} href={`/watch/${a.id}/1`} className="group block">
          <div className="overflow-hidden rounded-2xl border border-line/70 bg-card shadow-card transition hover:-translate-y-1 hover:border-sunrise/50">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={a.poster}
              alt={a.title}
              loading="lazy"
              className="aspect-[2/3] w-full object-cover transition duration-300 group-hover:scale-105"
            />
          </div>
          <div className="line-clamp-2 mt-2 text-[13px] font-bold">{a.title}</div>
          <div className="text-[11px] text-ink-mute">
            {a.score ? `★ ${a.score.toFixed(1)}` : ""}
          </div>
        </a>
      ))}
    </div>
  );
}

export function DiscoverPageBase({
  title,
  sort,
  hint,
}: {
  title: string;
  sort: string;
  hint?: string;
}) {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="mb-5 flex items-center gap-3">
        <span className="h-5 w-1.5 rounded-full bg-gradient-to-b from-sunrise to-sunrise-soft shadow-glow-sm" />
        <h1 className="text-lg font-extrabold tracking-wide">{title}</h1>
        {hint && <span className="text-xs text-ink-mute">{hint}</span>}
      </div>
      <Suspense fallback={<CardGridSkeleton n={12} />}>
        <Feed sort={sort} />
      </Suspense>
    </div>
  );
}
