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
    "User-Agent": UA,
    Accept: "*/*",
  };
  const range = req.headers.get("range");
  if (range) upstreamHeaders.Range = range;

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
    headers.set("Cache-Control", "no-store");
    const pass = ["content-type", "content-length", "content-range", "accept-ranges"];
    for (const h of pass) {
      const v = upstream.headers.get(h);
      if (v) headers.set(h, v);
    }
    if (!headers.has("content-type")) {
      headers.set("content-type", "application/octet-stream");
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
      "Access-Control-Allow-Headers": "Range, Content-Type",
    },
  });
}
