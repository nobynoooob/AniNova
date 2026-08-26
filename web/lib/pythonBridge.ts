import { StreamSource } from "./types";

/**
 * Python bridge: shells out to the desktop app's proven ProviderManager
 * (`python -m ani_cli_arabic.webstream`) so the web player uses the exact
 * same extraction chain as the desktop build — Miruro primary, full
 * fallbacks, warm-browser handling — with zero duplicated scraping logic.
 *
 * Enabled when the repo layout is present (self-hosted / dev). On Vercel or
 * any environment without the Python package, callers fall through to the
 * in-process AllAnime resolver.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const TIMEOUT_MS = 45000;

function findRepoRoot(): string | null {
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(dir, "ani_cli_arabic", "webstream.py"))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

export function pythonBridgeAvailable(): boolean {
  if (process.env.ANINOVA_PY_BRIDGE === "0") return false;
  return findRepoRoot() !== null;
}

export async function pythonResolve(
  title: string,
  episode: number,
  category: "sub" | "dub" | "ar_sub" = "sub"
): Promise<StreamSource[]> {
  const root = findRepoRoot();
  if (!root) throw new Error("python bridge unavailable (repo layout not found)");

  return new Promise<StreamSource[]>((resolvePromise, reject) => {
    const child = spawn(
      "python3",
      [
        "-m",
        "ani_cli_arabic.webstream",
        "--title",
        title,
        "--episode",
        String(episode),
        "--category",
        category,
        ...(category === "ar_sub" ? ["--lang", "ar"] : []),
      ],
      { cwd: root, env: { ...process.env, PYTHONUNBUFFERED: "1" } }
    );

    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error("python bridge timeout"));
    }, TIMEOUT_MS);

    child.stdout.on("data", (d) => (out += d.toString()));
    child.stderr.on("data", (d) => (err += d.toString()));
    child.on("error", (e) => {
      clearTimeout(timer);
      reject(new Error(`python bridge spawn failed: ${e.message}`));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      const line = out.trim().split("\n").filter(Boolean).pop() || "";
      try {
        const data = JSON.parse(line);
        if (!data.ok || !Array.isArray(data.sources) || !data.sources.length) {
          reject(new Error(data.error || "python bridge resolved nothing"));
          return;
        }
        const sources: StreamSource[] = data.sources.map(
          (s: {
            server?: string;
            url?: string;
            quality?: string;
            headers?: Record<string, string>;
            subtitles?: { url: string; lang: string; label?: string }[];
          }) => {
            const params = new URLSearchParams({ url: String(s.url || "") });
            if (s.headers?.Referer) params.set("referer", s.headers.Referer);
            if (s.headers?.["User-Agent"]) params.set("ua", s.headers["User-Agent"]);
            return {
              server: String(s.server || "primary"),
              url: `/api/stream?${params.toString()}`,
              quality: s.quality,
              subtitles: (s.subtitles || []).map((st) => ({
                url: `/api/stream?url=${encodeURIComponent(st.url)}`,
                lang: st.lang,
                label: st.label || st.lang,
              })),
            };
          }
        );
        resolvePromise(sources);
      } catch {
        reject(
          new Error(
            `python bridge bad output (exit ${code}): ${(err || line).slice(-160)}`
          )
        );
      }
    });
  });
}
