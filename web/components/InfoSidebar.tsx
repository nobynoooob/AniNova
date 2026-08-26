"use client";

import { AnimeInfo } from "@/lib/types";
import Image from "next/image";
import { useEffect, useState } from "react";
import { Flame, Heart, Laugh, ThumbsUp, Zap } from "lucide-react";

const EMOJIS = [
  { key: "fire", Icon: Flame, label: "Fire" },
  { key: "heart", Icon: Heart, label: "Love" },
  { key: "laugh", Icon: Laugh, label: "LOL" },
  { key: "shock", Icon: Zap, label: "Shock" },
  { key: "thumbs", Icon: ThumbsUp, label: "Nice" },
] as const;

/**
 * Metadata sidebar: poster card with tags, title/synopsis/genres and the
 * emoji reactions widget with live counters (persisted server-side).
 */
export default function InfoSidebar({
  info,
  episode,
}: {
  info: AnimeInfo;
  episode: number;
}) {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [voted, setVoted] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/reactions?animeId=${info.id}&episode=${episode}`)
      .then((r) => r.json())
      .then((d) => d.ok && setCounts(d.counts))
      .catch(() => {});
  }, [info.id, episode]);

  const vote = async (emoji: string) => {
    if (voted) return;
    setVoted(emoji);
    setCounts((c) => ({ ...c, [emoji]: (c[emoji] || 0) + 1 }));
    try {
      const res = await fetch("/api/reactions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ animeId: info.id, episode, emoji }),
      });
      const d = await res.json();
      if (d.ok) setCounts(d.counts);
    } catch {}
  };

  return (
    <div className="space-y-5">
      {/* Poster card */}
      <div className="overflow-hidden rounded-2xl border border-line/70 bg-card shadow-card">
        <div className="relative aspect-[2/3] w-full">
          {info.poster && (
            <Image
              src={info.poster}
              alt={info.title}
              fill
              sizes="300px"
              className="object-cover"
              priority
            />
          )}
          <div className="absolute left-2 top-2 flex gap-1.5">
            <span className="rounded-md bg-obsidian/85 px-2 py-0.5 text-[10px] font-extrabold text-sunrise-soft backdrop-blur-sm">
              HD
            </span>
            <span className="rounded-md bg-obsidian/85 px-2 py-0.5 text-[10px] font-extrabold text-ink-sec backdrop-blur-sm">
              {info.status?.toUpperCase() || "TV"}
            </span>
            {info.episodes ? (
              <span className="rounded-md bg-obsidian/85 px-2 py-0.5 text-[10px] font-extrabold text-ink-sec backdrop-blur-sm">
                {info.episodes} EPS
              </span>
            ) : null}
          </div>
        </div>
        <div className="p-4">
          <h2 className="text-base font-extrabold leading-snug">{info.title}</h2>
          {info.romaji && info.romaji !== info.title && (
            <div className="mt-1 text-xs text-ink-mute">{info.romaji}</div>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(info.genres || []).slice(0, 5).map((g) => (
              <span key={g} className="chip">
                {g}
              </span>
            ))}
          </div>
          {info.synopsis && (
            <p className="mt-3 line-clamp-3 text-[13px] leading-5 text-ink-sec">
              {info.synopsis}
            </p>
          )}
          <a
            href={`https://anilist.co/anime/${info.id}`}
            target="_blank"
            rel="noreferrer"
            className="btn-ghost mt-4 w-full"
          >
            View Full Details
          </a>
        </div>
      </div>

      {/* Reactions */}
      <div className="rounded-2xl border border-line/70 bg-card p-4">
        <div className="mb-3 text-[11px] font-extrabold uppercase tracking-wider text-ink-mute">
          React to episode {episode}
        </div>
        <div className="flex flex-wrap gap-2">
          {EMOJIS.map(({ key, Icon, label }) => (
            <button
              key={key}
              onClick={() => vote(key)}
              title={label}
              className={`flex items-center gap-1.5 rounded-2xl border px-3 py-2 text-xs
                          font-bold transition active:scale-95
                          ${voted === key
                            ? "border-sunrise bg-sunrise/15 text-sunrise-soft"
                            : "border-line bg-obsidian text-ink-sec hover:border-sunrise/60 hover:text-ink"}`}
            >
              <Icon size={15} className={voted === key ? "text-sunrise" : ""} />
              {counts[key] || 0}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
