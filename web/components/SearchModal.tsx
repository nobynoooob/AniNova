"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Search, X } from "lucide-react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimeSummary } from "@/lib/types";

export default function SearchModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<AnimeSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 60);
  }, [open]);

  // Debounced live search
  useEffect(() => {
    if (!open) return;
    const q2 = q.trim();
    if (!q2) {
      setItems([]);
      return;
    }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/anime/search?q=${encodeURIComponent(q2)}`);
        const data = await res.json();
        setItems(data.ok ? data.items : []);
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }, 280);
    return () => clearTimeout(t);
  }, [q, open]);

  const go = (id: string) => {
    onClose();
    router.push(`/watch/${id}/1`);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] flex items-start justify-center bg-black/70
                     backdrop-blur-sm px-4 pt-[12vh]"
          onClick={onClose}
        >
          <motion.div
            initial={{ y: -14, scale: 0.98 }}
            animate={{ y: 0, scale: 1 }}
            exit={{ y: -10, opacity: 0 }}
            transition={{ type: "spring", stiffness: 320, damping: 28 }}
            className="w-full max-w-2xl overflow-hidden rounded-3xl border border-line
                       bg-surface shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-line/70 px-5 py-4">
              <Search size={18} className="text-sunrise" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && items[0]) go(items[0].id);
                  if (e.key === "Escape") onClose();
                }}
                placeholder="Search anime by title…"
                className="flex-1 bg-transparent text-base outline-none placeholder:text-ink-mute"
              />
              <button onClick={onClose} className="text-ink-mute hover:text-ink">
                <X size={18} />
              </button>
            </div>

            <div className="max-h-[55vh] overflow-y-auto p-2">
              {loading && (
                <div className="p-6 text-center text-sm text-ink-mute">Searching…</div>
              )}
              {!loading && q && !items.length && (
                <div className="p-6 text-center text-sm text-ink-mute">
                  No matches — try another title.
                </div>
              )}
              {!q && (
                <div className="p-6 text-center text-sm text-ink-mute">
                  Type to search across every anime. Enter opens the first hit.
                </div>
              )}
              {items.map((a) => (
                <button
                  key={a.id}
                  onClick={() => go(a.id)}
                  className="flex w-full items-center gap-4 rounded-2xl p-2.5 text-left
                             transition hover:bg-card"
                >
                  <Image
                    src={a.poster}
                    alt=""
                    width={44}
                    height={62}
                    className="h-[62px] w-[44px] rounded-lg object-cover"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-bold">{a.title}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-mute">
                      {a.year && <span>{a.year}</span>}
                      {a.format && <span className="uppercase">{a.format}</span>}
                      {a.score ? <span className="text-sunrise-soft">★ {a.score.toFixed(1)}</span> : null}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
