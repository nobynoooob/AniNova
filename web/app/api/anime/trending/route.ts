import { NextResponse } from "next/server";
import { fetchTrending } from "@/lib/anilist";

export const revalidate = 300;

export async function GET() {
  try {
    const items = await fetchTrending(24);
    return NextResponse.json({ ok: true, items });
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: String(e instanceof Error ? e.message : e), items: [] },
      { status: 502 }
    );
  }
}
