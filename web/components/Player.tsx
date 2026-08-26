"use client";

/**
 * ArtPlayer + hls.js HLS player.
 * Loaded client-side only (dynamic import in the watch page) because both
 * libraries touch window at import time.
 */
import { useEffect, useRef, useState } from "react";

interface PlayerProps {
  source: string | null;      // proxied url (/api/stream?url=...)
  poster?: string;
  autoPlay: boolean;
  onEnded: () => void;
  onError: (err: string) => void;
  onReady?: () => void;
}

export default function Player({
  source,
  poster,
  autoPlay,
  onEnded,
  onError,
  onReady,
}: PlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const artRef = useRef<any>(null);
  const [status, setStatus] = useState<string>("idle");
  // LEVEL_LOAD_ERROR retry budget: transient CDN hiccups get an automatic
  // reload before we escalate to server fallback.
  const hlsRetries = useRef(0);

  useEffect(() => {
    let disposed = false;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let hls: any = null;
    hlsRetries.current = 0;

    async function build() {
      if (!containerRef.current || !source) return;
      setStatus("loading");
      const [{ default: Artplayer }, HlsMod] = await Promise.all([
        import("artplayer"),
        import("hls.js"),
      ]);
      const Hls = (HlsMod as { default: typeof import("hls.js").default }).default;

      if (disposed || !containerRef.current) return;
      containerRef.current.innerHTML = "";

      const playM3u8 = (video: HTMLVideoElement, url: string, art: unknown) => {
        if (Hls.isSupported()) {
          if (hls) hls.destroy();
          hls = new Hls({
            maxBufferLength: 60,
            maxMaxBufferLength: 180,
            // All requests already flow through /api/stream (same-origin),
            // but keep credentials off so proxied CORS stays simple.
            xhrSetup: (xhr: XMLHttpRequest) => {
              xhr.withCredentials = false;
            },
          });
          hls.loadSource(url);
          hls.attachMedia(video);
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          hls.on(Hls.Events.MANIFEST_PARSED, () => (art as any)?.play());
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          hls.on(Hls.Events.ERROR, (_e: unknown, data: any) => {
            if (!data?.fatal) return;
            const loadErrors = new Set([
              Hls.ErrorDetails.LEVEL_LOAD_ERROR,
              Hls.ErrorDetails.LEVEL_LOAD_TIMEOUT,
              Hls.ErrorDetails.MANIFEST_LOAD_ERROR,
              Hls.ErrorDetails.MANIFEST_LOAD_TIMEOUT,
            ]);
            if (
              loadErrors.has(data.details) &&
              hlsRetries.current < 2 &&
              !disposed
            ) {
              // Automatic proxied reload: transient CDN hiccup or a stale
              // manifest — retry through the same /api/stream route.
              hlsRetries.current += 1;
              setStatus("loading");
              setTimeout(() => {
                if (disposed || !hls) return;
                hls.loadSource(
                  url + (url.includes("?") ? "&" : "?") +
                    `_r=${hlsRetries.current}`
                );
                hls.startLoad();
              }, 800 * hlsRetries.current);
              return;
            }
            setStatus("error");
            onError(`HLS fatal: ${data.details || "unknown"}`);
          });
        } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
          // Safari native HLS
          video.src = url;
          video.addEventListener("loadedmetadata", () => (art as any)?.play());
        } else {
          setStatus("error");
          onError("HLS is not supported in this browser");
        }
      };

      artRef.current = new Artplayer({
        container: containerRef.current,
        url: source,
        poster: poster || undefined,
        volume: 0.8,
        autoplay: autoPlay,
        autoMini: false,
        fullscreen: true,
        fullscreenWeb: true,
        pip: true,
        setting: true,
        playbackRate: true,
        aspectRatio: true,
        flip: true,
        hotkey: true,
        theme: "#FF7A00",
        moreVideoAttr: {
          crossOrigin: "anonymous",
          playsInline: true,
        },
        customType: { m3u8: playM3u8 },
        type: "m3u8",
      });

      artRef.current.on("video:ended", () => onEnded());
      artRef.current.on("video:error", () => {
        setStatus("error");
        onError("video element error");
      });
      artRef.current.on("ready", () => {
        setStatus("ready");
        onReady?.();
      });
    }

    build();
    return () => {
      disposed = true;
      try {
        if (hls) hls.destroy();
      } catch {}
      try {
        artRef.current?.destroy(false);
      } catch {}
      artRef.current = null;
    };
    // Rebuild only when the actual source changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  return (
    <div className="relative w-full">
      <div
        ref={containerRef}
        className="aspect-video w-full overflow-hidden rounded-2xl border border-line/70 bg-black"
      />
      {status === "loading" && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="h-12 w-12 animate-spin rounded-full border-4 border-line border-t-sunrise" />
        </div>
      )}
    </div>
  );
}
