import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36";

const BLOCKED_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "::1",
  "metadata.google.internal",
]);

/**
 * CORS-hardened stream proxy.
 * GET /api/stream?url=<upstream m3u8/mp4>
 * Strips referer/origin requirements and pipes bytes through with permissive
 * CORS so the browser player can load cross-origin HLS.
 */
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const raw = searchParams.get("url") || "";
  let target: URL;
  try {
    target = new URL(raw);
  } catch {
    return NextResponse.json({ error: "invalid url" }, { status: 400 });
  }
  if (!/^https?:$/.test(target.protocol) || BLOCKED_HOSTS.has(target.hostname)) {
    return NextResponse.json({ error: "blocked host" }, { status: 400 });
  }

  const upstreamHeaders: Record<string, string> = {
    "User-Agent": searchParams.get("ua") || UA,
    Accept: "*/*",
  };
  const referer = searchParams.get("referer");
  if (referer) upstreamHeaders.Referer = referer;
  const range = req.headers.get("range");
  if (range) upstreamHeaders.Range = range;

  /**
   * Rewrite every URL inside an HLS manifest to route back through this
   * proxy. Without this, hls.js resolves the playlist's RELATIVE segment /
   * variant / key URIs against localhost (e.g. /api/1080p/index.m3u8) and
   * dies with LEVEL_LOAD_ERROR.
   *
   * Handles: variant playlist lines, media segment lines, and URI="…"
   * attributes (#EXT-X-KEY, #EXT-X-MAP, #EXT-X-MEDIA). The original referer
   * and UA are encoded into every proxied child URL so segment fetches keep
   * the upstream CDN's required headers.
   */
  function rewriteM3u8(bodyText: string, baseUrl: string): string {
    const wrap = (u: string): string => {
      if (!u || /^(data|blob):/i.test(u)) return u;
      try {
        const abs = new URL(u, baseUrl).toString();
        const p = new URLSearchParams({ url: abs });
        if (referer) p.set("referer", referer);
        const ownUa = searchParams.get("ua");
        if (ownUa) p.set("ua", ownUa);
        return `/api/stream?${p.toString()}`;
      } catch {
        return u;
      }
    };
    return bodyText
      .split(/\r?\n/)
      .map((line) => {
        const t = line.trim();
        if (!t) return line;
        if (t.startsWith("#")) {
          // Attribute URIs (keys, init segments, alternate audio/subs)
          return line.replace(/URI="([^"]+)"/g, (_m, u) => `URI="${wrap(u)}"`);
        }
        return wrap(t);
      })
      .join("\n");
  }

  try {
    const upstream = await fetch(target.toString(), {
      headers: upstreamHeaders,
      redirect: "follow",
      cache: "no-store",
    });
    if (!upstream.ok && upstream.status !== 206) {
      return NextResponse.json(
        { error: `upstream ${upstream.status}` },
        { status: 502 }
      );
    }
    const headers = new Headers();
    headers.set("Access-Control-Allow-Origin", "*");
    headers.set("Access-Control-Allow-Headers", "*");
    headers.set("Cache-Control", "no-store");
    const pass = ["content-type", "content-length", "content-range", "accept-ranges"];
    for (const h of pass) {
      const v = upstream.headers.get(h);
      if (v) headers.set(h, v);
    }
    if (!headers.has("content-type")) {
      headers.set("content-type", "application/octet-stream");
    }

    // HLS manifests: rewrite inner URLs instead of piping raw bytes.
    const ct = (headers.get("content-type") || "").toLowerCase();
    const isM3u8 =
      ct.includes("mpegurl") ||
      ct.includes("m3u") ||
      target.pathname.toLowerCase().endsWith(".m3u8");
    if (isM3u8) {
      const text = await upstream.text();
      headers.set("content-type", "application/vnd.apple.mpegurl");
      headers.delete("content-length");
      return new NextResponse(rewriteM3u8(text, target.toString()), {
        status: 200,
        headers,
      });
    }

    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch (e) {
    return NextResponse.json(
      { error: String(e instanceof Error ? e.message : e) },
      { status: 502 }
    );
  }
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "*",
    },
  });
}
