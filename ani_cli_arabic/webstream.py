"""
Headless stream resolver for the AniNova web app.

Invoked by the Next.js API layer as a subprocess:
    python -m ani_cli_arabic.webstream --title "One Piece" --episode 4

Reuses the desktop ProviderManager chain (Miruro primary — verified working),
so the web and desktop extraction logic stay in sync and benefit from the
same fixes (browser auto-heal, provider fallbacks, warm browser, etc).

Output: single JSON line on stdout:
    {"ok": true, "sources": [{"server": "...", "url": "...", "quality": "..."}]}
"""

import argparse
import json
import sys


def resolve_arabic(title: str, episode: float, category: str):
    """Arabic pipeline (ani-cli-ar AnimeAPI): search -> episodes ->
    streaming servers -> Mediafire direct URL. Quality keys map to the
    Arabic hosters' variants and double as server chips in the UI."""
    from ani_cli_arabic.api import AnimeAPI

    api = AnimeAPI()
    results = api.search_anime(title)
    if not results:
        raise RuntimeError("not found in the Arabic catalog")

    def _score(r):
        t = (getattr(r, "title_en", "") or "").lower()
        j = (getattr(r, "title_jp", "") or "").lower()
        needle = title.lower()
        return 0 if needle in t or t in needle else (
            1 if needle in j or j in needle else 2)

    anime = sorted(results, key=_score)[0]
    eps = api.get_episodes(anime.id)
    if not eps:
        raise RuntimeError("no episodes in the Arabic catalog")
    target = str(int(episode))
    selected = None
    for ep in eps:
        if str(ep.display_num) == target or str(ep.number) == target:
            selected = ep
            break
    if selected is None:
        raise RuntimeError(f"episode {target} missing in the Arabic catalog")

    ctx = {"anime": title, "episode": str(selected.display_num),
           "provider": "arabic_api"}
    server_data = api.get_streaming_servers(
        anime.id, str(selected.number), anime.type, ctx)
    if not server_data:
        raise RuntimeError("Arabic server list unavailable")

    current_ep = server_data.get("CurrentEpisode") or {}
    quality_keys = [
        ("1080p", "FRFhdQ"), ("720p", "FRLink"), ("480p", "FRLowQ"),
    ]
    sources = []
    for label, key in quality_keys:
        server_id = current_ep.get(key) or current_ep.get("FRLink")
        if not server_id:
            continue
        mf_url = api.build_mediafire_url(server_id)
        direct = api.extract_mediafire_direct(mf_url, ctx)
        if direct:
            sources.append({
                "server": f"arabic-{label}",
                "url": direct,
                "quality": label,
                # Arabic API streams carry baked-in Arabic subtitles
                "subtitles": [],
            })
            break  # one working direct URL is enough; quality from key
    if not sources:
        raise RuntimeError("Arabic direct URL extraction failed")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(prog="webstream")
    parser.add_argument("--title", required=True)
    parser.add_argument("--episode", required=True, type=float)
    parser.add_argument("--category", default="sub",
                        choices=["sub", "dub", "ar_sub"])
    parser.add_argument("--lang", default=None,
                        help="language override (ar routes to the Arabic pipeline)")
    parser.add_argument("--timeout", type=float, default=40.0)
    args = parser.parse_args()

    lang = (args.lang or "").lower()
    is_arabic = lang == "ar" or args.category == "ar_sub"

    try:
        if is_arabic:
            sources = resolve_arabic(args.title, args.episode, args.category)
        else:
            from ani_cli_arabic.scrapers.provider_manager import ProviderManager
            import asyncio

            pm = ProviderManager()

            async def run():
                return await pm.resolve_stream(
                    args.title, args.episode,
                    mode=args.category if args.category in ("sub", "dub") else "sub",
                    language="english",
                    provider="auto",
                    quiet=True,
                )

            url, headers, provider = asyncio.run(run())
            if not url:
                print(json.dumps({
                    "ok": False,
                    "error": "no stream resolved by provider chain",
                    "sources": [],
                }))
                return 1
            sources = [{
                "server": (provider or "primary").lower(),
                "url": url,
                "quality": "auto",
                "headers": headers or {},
                "subtitles": [],
            }]
    except Exception as exc:  # never emit a traceback to the JSON channel
        print(json.dumps({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "sources": [],
        }))
        return 1

    print(json.dumps({
        "ok": True,
        "pipeline": "arabic" if is_arabic else "english",
        "sources": sources,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
