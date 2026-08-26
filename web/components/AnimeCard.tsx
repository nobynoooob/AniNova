import Image from "next/image";
import Link from "next/link";
import { AnimeSummary } from "@/lib/types";

export function AnimeCard({
  anime,
  priority = false,
}: {
  anime: AnimeSummary;
  priority?: boolean;
}) {
  return (
    <Link
      href={`/watch/${anime.id}/1`}
      className="group relative block overflow-hidden rounded-2xl border border-line/70
                 bg-card shadow-card transition duration-200
                 hover:-translate-y-1 hover:border-sunrise/50 hover:shadow-glow-sm"
    >
      <div className="relative aspect-[2/3] w-full overflow-hidden">
        {anime.poster ? (
          <Image
            src={anime.poster}
            alt={anime.title}
            fill
            sizes="(max-width:640px) 45vw, (max-width:1024px) 25vw, 200px"
            className="object-cover transition duration-300 group-hover:scale-105"
            priority={priority}
          />
        ) : (
          <div className="skeleton h-full w-full" />
        )}
        <div
          className="pointer-events-none absolute inset-0 bg-gradient-to-t
                      from-obsidian/90 via-transparent to-transparent opacity-0
                      transition group-hover:opacity-100"
        />
        {anime.score ? (
          <span
            className="absolute left-2 top-2 rounded-full bg-obsidian/80 px-2 py-0.5
                        text-[11px] font-extrabold text-sunrise-soft backdrop-blur-sm"
          >
            ★ {anime.score.toFixed(1)}
          </span>
        ) : null}
        <span className="absolute right-2 top-2 rounded-full bg-gradient-to-br from-sunrise
                          to-sunrise-soft px-2 py-0.5 text-[10px] font-extrabold uppercase
                          tracking-wider text-white opacity-0 transition group-hover:opacity-100">
          Watch
        </span>
      </div>
      <div className="p-3">
        <div className="line-clamp-2 min-h-[2.6em] text-[13px] font-bold leading-snug">
          {anime.title}
        </div>
        <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-mute">
          {anime.year && <span>{anime.year}</span>}
          {anime.format && (
            <span className="uppercase tracking-wide">{anime.format}</span>
          )}
        </div>
      </div>
    </Link>
  );
}

export function CardGrid({
  items,
  priorityCount = 0,
}: {
  items: AnimeSummary[];
  priorityCount?: number;
}) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
      {items.map((a, i) => (
        <AnimeCard key={a.id} anime={a} priority={i < priorityCount} />
      ))}
    </div>
  );
}

export function CardGridSkeleton({ n = 12 }: { n?: number }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="overflow-hidden rounded-2xl border border-line/70 bg-card">
          <div className="skeleton aspect-[2/3] w-full" />
          <div className="p-3">
            <div className="skeleton h-3 w-full rounded-md" />
            <div className="skeleton mt-2 h-3 w-1/2 rounded-md" />
          </div>
        </div>
      ))}
    </div>
  );
}
