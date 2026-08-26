import { NextResponse } from "next/server";
import { searchAnime } from "@/lib/anilist";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = (searchParams.get("q") || "").trim();
  const page = parseInt(searchParams.get("page") || "1", 10);
  if (!q) {
    return NextResponse.json({ ok: false, error: "missing q", items: [] });
  }
  try {
    const { items, info } = await searchAnime(q, page);
    return NextResponse.json({ ok: true, items, info });
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: String(e instanceof Error ? e.message : e), items: [] },
      { status: 502 }
    );
  }
}
