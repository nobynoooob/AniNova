"use client";

import { EpisodeEntry } from "@/lib/types";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useMemo, useState } from "react";

/**
 * Episode drawer: range pagination (001-100 / 101-200 / ...), quick number
 * search, and a grid of tappable episode buttons with the active one
 * highlighted in Sunrise orange.
 */
export default function EpisodeDrawer({
  episodes,
  current,
  onSelect,
}: {
  episodes: EpisodeEntry[];
  current: number;
  onSelect: (num: number) => void;
}) {
  const [filter, setFilter] = useState("");
  const [rangeIdx, setRangeIdx] = useState(0);

  const ranges = useMemo(() => {
    const out: { from: number; to: number }[] = [];
    for (let i = 0; i < episodes.length; i += 100) {
      out.push({ from: episodes[i].num, to: episodes[Math.min(i + 99, episodes.length - 1)].num });
    }
    return out;
  }, [episodes]);

  // Keep the range containing the current episode selected
  const activeRange = useMemo(() => {
    const idx = ranges.findIndex((r) => current >= r.from && current <= r.to);
    return idx >= 0 ? idx : rangeIdx;
  }, [ranges, current, rangeIdx]);

  const range = ranges[Math.min(activeRange, Math.max(0, ranges.length - 1))];
  const filtered = useMemo(() => {
    if (!range) return [];
    const inRange = episodes.filter(
      (e) => e.num >= range.from && e.num <= range.to
    );
    if (!filter.trim()) return inRange;
    const q = filter.replace(/[^0-9.]/g, "");
    return inRange.filter((e) => String(e.num).startsWith(q));
  }, [episodes, range, filter]);

  if (!episodes.length) {
    return (
      <div className="rounded-2xl border border-line/70 bg-card p-6 text-center text-sm text-ink-mute">
        Episode list unavailable upstream.
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-line/70 bg-card">
      <div className="border-b border-line/60 p-4">
        {/* Range pager */}
        <div className="mb-3 flex items-center gap-2">
          <button
            onClick={() => setRangeIdx(Math.max(0, activeRange - 1))}
            disabled={activeRange <= 0}
            className="btn-ghost !px-2 !py-1.5"
            aria-label="Previous range"
          >
            <ChevronLeft size={16} />
          </button>
          <div className="flex-1 truncate text-center text-xs font-extrabold tracking-wider text-ink-sec">
            EPS: {String(range?.from ?? 1).padStart(3, "0")}–
            {String(range?.to ?? 100).padStart(3, "0")}
          </div>
          <button
            onClick={() => setRangeIdx(Math.min(ranges.length - 1, activeRange + 1))}
            disabled={activeRange >= ranges.length - 1}
            className="btn-ghost !px-2 !py-1.5"
            aria-label="Next range"
          >
            <ChevronRight size={16} />
          </button>
        </div>
        {/* Quick search */}
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-mute" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Find episode…"
            inputMode="numeric"
            className="w-full rounded-xl border border-line bg-obsidian py-2 pl-9 pr-3 text-sm
                       outline-none transition focus:border-sunrise"
          />
        </div>
      </div>

      <div className="grid max-h-[420px] grid-cols-5 gap-2 overflow-y-auto p-4
                      sm:max-h-[520px] lg:grid-cols-4 xl:grid-cols-5">
        {filtered.map((e) => (
          <button
            key={e.id}
            onClick={() => onSelect(e.num)}
            className={`aspect-square rounded-xl border text-sm font-bold transition
                        ${e.num === current
                          ? "border-transparent bg-gradient-to-br from-sunrise to-sunrise-soft text-white shadow-glow-sm"
                          : "border-line bg-obsidian text-ink-sec hover:border-sunrise hover:text-ink"}`}
            title={e.title || `Episode ${e.num}`}
          >
            {e.num}
          </button>
        ))}
        {!filtered.length && (
          <div className="col-span-full py-6 text-center text-sm text-ink-mute">
            No episodes match.
          </div>
        )}
      </div>
    </div>
  );
}
