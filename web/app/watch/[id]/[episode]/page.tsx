"use client";

import EpisodeDrawer from "@/components/EpisodeDrawer";
import InfoSidebar from "@/components/InfoSidebar";
import Player from "@/components/Player";
import { AnimeInfo, EpisodeEntry, StreamSource } from "@/lib/types";
import { ArrowLeft, ArrowRight, Download, Monitor, Play } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

const AUDIO_MODES = ["SUB", "DUB", "AR SUB"] as const;

export default function WatchPage() {
  const params = useParams<{ id: string; episode: string }>();
  const router = useRouter();
  const animeId = params.id;
  const episode = parseInt(params.episode, 10) || 1;

  const [info, setInfo] = useState<AnimeInfo | null>(null);
  const [episodes, setEpisodes] = useState<EpisodeEntry[]>([]);
  const [episodesError, setEpisodesError] = useState<string | null>(null);
  const [sources, setSources] = useState<StreamSource[]>([]);
  const [serverIdx, setServerIdx] = useState(0);
  const [loadingStream, setLoadingStream] = useState(true);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [audio, setAudio] = useState<"SUB" | "DUB" | "AR SUB">("SUB");
  const [autoPlay, setAutoPlay] = useState(true);
  const [autoNext, setAutoNext] = useState(true);
  const [theater, setTheater] = useState(false);
  const [mobileTab, setMobileTab] = useState<"episodes" | "info">("episodes");

  // Load metadata + episode list once
  useEffect(() => {
    let alive = true;
    setInfo(null);
    setEpisodes([]);
    fetch(`/api/anime/info/${animeId}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (d.ok) {
          setInfo(d.info);
          setEpisodes(d.episodes || []);
          setEpisodesError(d.episodesError || null);
        } else {
          setEpisodesError(d.error || "failed to load");
        }
      })
      .catch(() => alive && setEpisodesError("network error"));
    return () => {
      alive = false;
    };
  }, [animeId]);

  // Resolve streams for the current episode (server fallback chain)
  const resolve = useCallback(
    async (startIdx: number) => {
      if (!info?.title) return;
      setLoadingStream(true);
      setStreamError(null);
      setSources([]);
      setServerIdx(0);
      try {
        const cat = audio === "SUB" ? "sub" : audio === "DUB" ? "dub" : "ar_sub";
        const res = await fetch(
          `/api/anime/stream?title=${encodeURIComponent(info.title)}` +
            `&episode=${episode}&category=${cat}`
        );
        const data = await res.json();
        if (!data.ok || !data.sources?.length) {
          throw new Error(data.error || "no sources");
        }
        setSources(data.sources);
        // Probe the requested server first; on failure walk the chain.
        for (let i = startIdx; i < data.sources.length; i++) {
          setServerIdx(i);
          const probe = await fetch(data.sources[i].url, {
            method: "HEAD",
          }).catch(() => null);
          if (!probe || probe.ok) {
            setLoadingStream(false);
            return;
          }
          setStreamError(`server "${data.sources[i].server}" unreachable`);
        }
        // All HEAD probes failed — hand the first to the player anyway and
        // let its own error handling decide (some hosts reject HEAD).
        setServerIdx(0);
        setLoadingStream(false);
      } catch (e) {
        setStreamError(String(e instanceof Error ? e.message : e));
        setLoadingStream(false);
      }
    },
    [info?.title, episode, audio]
  );

  useEffect(() => {
    resolve(0);
  }, [resolve]);

  const currentSource = sources[serverIdx] || null;

  // Prev / next navigation
  const goEpisode = useCallback(
    (num: number) => router.push(`/watch/${animeId}/${num}`),
    [animeId, router]
  );
  const nextEp = useMemo(
    () => episodes.find((e) => e.num === episode + 1)?.num ?? null,
    [episodes, episode]
  );
  const prevEp = useMemo(
    () => episodes.find((e) => e.num === episode - 1)?.num ?? null,
    [episodes, episode]
  );

  const toggleCls = (on: boolean) =>
    `flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-bold transition ${
      on
        ? "border-sunrise bg-sunrise/15 text-sunrise-soft"
        : "border-line bg-obsidian text-ink-mute hover:text-ink"
    }`;

  const Toggle = ({
    on,
    onClick,
    label,
  }: {
    on: boolean;
    onClick: () => void;
    label: string;
  }) => (
    <button onClick={onClick} className={toggleCls(on)}>
      <span
        className={`relative h-4 w-7 rounded-full transition ${
          on ? "bg-sunrise" : "bg-line"
        }`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
            on ? "left-3.5" : "left-0.5"
          }`}
        />
      </span>
      {label}
    </button>
  );

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-6">
      {/* Breadcrumb */}
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-mute">
        <Link href="/" className="hover:text-sunrise-soft">
          Home
        </Link>
        <span>/</span>
        <Link href="/categories" className="hover:text-sunrise-soft">
          {info?.title || "Anime"}
        </Link>
        <span>/</span>
        <span className="text-ink-sec">Episode {episode}</span>
      </div>

      {/* 3-column grid */}
      <div
        className={`grid gap-5 ${
          theater
            ? "grid-cols-1"
            : "lg:grid-cols-[300px_minmax(0,1fr)_320px]"
        }`}
      >
        {/* LEFT: episode drawer (desktop) */}
        {!theater && (
          <aside className="hidden lg:block">
            <EpisodeDrawer
              episodes={episodes}
              current={episode}
              onSelect={goEpisode}
            />
          </aside>
        )}

        {/* CENTER: player + controls */}
        <section className="min-w-0">
          <Player
            source={currentSource?.url || null}
            poster={info?.banner || info?.poster}
            autoPlay={autoPlay}
            onEnded={() => {
              if (autoNext && nextEp) goEpisode(nextEp);
            }}
            onError={(msg) => {
              // Automatic server fallback: try the next source seamlessly
              if (serverIdx + 1 < sources.length) {
                setServerIdx((i) => i + 1);
              } else {
                setStreamError(msg);
              }
            }}
          />

          {/* Status line */}
          <div className="mt-3 flex items-center justify-between text-xs text-ink-mute">
            <span>
              {loadingStream
                ? "Resolving stream…"
                : streamError
                  ? `⚠ ${streamError}`
                  : `Playing via server: ${currentSource?.server || "—"}`}
            </span>
            <button
              onClick={() => setTheater((v) => !v)}
              className="flex items-center gap-1.5 hover:text-sunrise-soft"
            >
              <Monitor size={14} /> Theater {theater ? "Off" : "Mode"}
            </button>
          </div>

          {/* Control bar */}
          <div className="mt-3 flex flex-wrap items-center gap-2.5 rounded-2xl border border-line/70 bg-card p-3">
            <Toggle on={autoPlay} onClick={() => setAutoPlay((v) => !v)} label="Auto-Play" />
            <Toggle on={autoNext} onClick={() => setAutoNext((v) => !v)} label="Auto-Next" />
            <div className="flex-1" />
            <button
              onClick={() => prevEp && goEpisode(prevEp)}
              disabled={!prevEp}
              className="btn-ghost disabled:opacity-40"
            >
              <ArrowLeft size={15} /> Prev
            </button>
            <button
              onClick={() => nextEp && goEpisode(nextEp)}
              disabled={!nextEp}
              className="btn-ghost disabled:opacity-40"
            >
              Next <ArrowRight size={15} />
            </button>
            <a
              href={currentSource?.url || "#"}
              download
              className="btn-ghost"
              title="Download stream"
            >
              <Download size={15} /> Download
            </a>
          </div>

          {/* Server & audio switcher */}
          <div className="mt-4 rounded-2xl border border-line/70 bg-card p-4">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-extrabold uppercase tracking-wider text-ink-mute">
                  Audio
                </span>
                {AUDIO_MODES.map((m) => (
                  <button
                    key={m}
                    onClick={() => setAudio(m)}
                    className={`chip ${audio === m ? "chip-active" : ""}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-extrabold uppercase tracking-wider text-ink-mute">
                  Server
                </span>
                {sources.length ? (
                  sources.map((s, i) => (
                    <button
                      key={s.url}
                      onClick={() => setServerIdx(i)}
                      className={`chip capitalize ${i === serverIdx ? "chip-active" : ""}`}
                    >
                      {s.server}
                    </button>
                  ))
                ) : (
                  <span className="text-xs text-ink-mute">
                    {loadingStream ? "resolving…" : "none"}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Mobile tabs: episodes / info */}
          <div className="mt-5 lg:hidden">
            <div className="mb-3 flex gap-2">
              <button
                onClick={() => setMobileTab("episodes")}
                className={`chip flex-1 justify-center !py-2 ${mobileTab === "episodes" ? "chip-active" : ""}`}
              >
                Episodes
              </button>
              <button
                onClick={() => setMobileTab("info")}
                className={`chip flex-1 justify-center !py-2 ${mobileTab === "info" ? "chip-active" : ""}`}
              >
                Details
              </button>
            </div>
            {mobileTab === "episodes" ? (
              <EpisodeDrawer
                episodes={episodes}
                current={episode}
                onSelect={goEpisode}
              />
            ) : info ? (
              <InfoSidebar info={info} episode={episode} />
            ) : null}
          </div>
        </section>

        {/* RIGHT: metadata sidebar (desktop) */}
        {!theater && (
          <aside className="hidden lg:block">
            {info ? (
              <InfoSidebar info={info} episode={episode} />
            ) : (
              <div className="space-y-4">
                <div className="skeleton aspect-[2/3] rounded-2xl" />
                <div className="skeleton h-4 w-3/4 rounded-md" />
                <div className="skeleton h-3 w-full rounded-md" />
              </div>
            )}
          </aside>
        )}
      </div>

      {/* Episode-list error hint */}
      {episodesError && !episodes.length && (
        <div className="mt-4 rounded-2xl border border-line/70 bg-card p-4 text-sm text-ink-mute">
          <Play size={14} className="mr-1.5 inline text-sunrise" />
          Episode list unavailable ({episodesError}). Playback search still
          works — use the player controls above.
        </div>
      )}
    </div>
  );
}
