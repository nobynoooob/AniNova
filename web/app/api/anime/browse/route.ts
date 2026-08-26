import { NextResponse } from "next/server";
import { fetchBrowse } from "@/lib/anilist";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const genre = searchParams.get("genre") || "";
  const sort = searchParams.get("sort") || "TRENDING_DESC";
  const season = (searchParams.get("season") || "") as "" | "current" | "upcoming";
  const page = parseInt(searchParams.get("page") || "1", 10);
  try {
    const { items, info } = await fetchBrowse({ genre, sort, season, page });
    return NextResponse.json({ ok: true, items, info });
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: String(e instanceof Error ? e.message : e), items: [] },
      { status: 502 }
    );
  }
}
