"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Search, Tv, Compass, Library, Calendar, Trophy, Film, Menu, X } from "lucide-react";
import SearchModal from "./SearchModal";

const LINKS = [
  { href: "/", label: "Home", icon: Tv },
  { href: "/categories", label: "Categories", icon: Compass },
  { href: "/library", label: "Library", icon: Library },
  { href: "/schedule", label: "Schedule", icon: Calendar },
  { href: "/top", label: "Top Anime", icon: Trophy },
  { href: "/movies", label: "Movies", icon: Film },
];

export default function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const [searchOpen, setSearchOpen] = useState(false);
  const [audio, setAudio] = useState<"sub" | "dub">("sub");
  const [menuOpen, setMenuOpen] = useState(false);

  // Ctrl+K / Cmd+K opens the global search modal
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Persist audio preference (Sub/Dub) across the session
  useEffect(() => {
    const saved = window.localStorage.getItem("aninova-audio");
    if (saved === "dub" || saved === "sub") setAudio(saved);
  }, []);
  const toggleAudio = useCallback(() => {
    setAudio((prev) => {
      const next = prev === "sub" ? "dub" : "sub";
      window.localStorage.setItem("aninova-audio", next);
      return next;
    });
  }, []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <>
      <header className="sticky top-0 z-50 glass">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-1.5 shrink-0">
            <span className="text-lg font-extrabold tracking-wide">
              AniNova <span className="sunrise-text">AR</span>
            </span>
            <span className="h-2 w-2 rounded-full bg-sunrise shadow-glow-sm animate-pulse" />
          </Link>

          {/* Desktop links */}
          <nav className="hidden lg:flex items-center gap-1 ml-4">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-2xl px-3.5 py-2 text-sm font-semibold transition ${
                  isActive(l.href)
                    ? "bg-sunrise/15 text-sunrise-soft shadow-glow-sm"
                    : "text-ink-sec hover:text-ink hover:bg-card"
                }`}
              >
                {l.label}
              </Link>
            ))}
          </nav>

          <div className="flex-1" />

          {/* Search trigger */}
          <button
            onClick={() => setSearchOpen(true)}
            className="hidden md:flex items-center gap-2 rounded-2xl border border-line bg-card/70
                       px-3.5 py-2 text-sm text-ink-mute transition hover:border-sunrise/60"
          >
            <Search size={16} />
            <span className="hidden xl:inline">Search anime…</span>
            <kbd
              className="ml-2 rounded-md border border-line bg-obsidian px-1.5 py-0.5
                         text-[10px] font-bold text-ink-mute"
            >
              Ctrl K
            </kbd>
          </button>

          {/* Sub/Dub toggle */}
          <button
            onClick={toggleAudio}
            title="Preferred audio track"
            className="chip !px-3 !py-1.5"
          >
            {audio.toUpperCase()}
          </button>

          {/* Avatar */}
          <div
            className="hidden sm:flex h-9 w-9 items-center justify-center rounded-full
                        bg-gradient-to-br from-sunrise to-sunrise-soft text-sm font-extrabold text-white
                        shadow-glow-sm cursor-pointer"
            title="Profile"
          >
            AR
          </div>

          {/* Mobile menu */}
          <button
            className="lg:hidden btn-ghost !px-2.5"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Menu"
          >
            {menuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>

        {/* Mobile drawer */}
        {menuOpen && (
          <nav className="lg:hidden border-t border-line/60 bg-surface/95 px-4 py-3 space-y-1">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setMenuOpen(false)}
                className={`flex items-center gap-3 rounded-2xl px-4 py-2.5 text-sm font-semibold ${
                  isActive(l.href)
                    ? "bg-sunrise/15 text-sunrise-soft"
                    : "text-ink-sec hover:bg-card"
                }`}
              >
                <l.icon size={16} />
                {l.label}
              </Link>
            ))}
            <button
              onClick={() => {
                setMenuOpen(false);
                setSearchOpen(true);
              }}
              className="flex w-full items-center gap-3 rounded-2xl px-4 py-2.5 text-sm
                         font-semibold text-ink-sec hover:bg-card"
            >
              <Search size={16} /> Search
            </button>
          </nav>
        )}
      </header>

      <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  );
}
