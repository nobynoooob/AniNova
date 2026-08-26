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


def main() -> int:
    parser = argparse.ArgumentParser(prog="webstream")
    parser.add_argument("--title", required=True)
    parser.add_argument("--episode", required=True, type=float)
    parser.add_argument("--category", default="sub",
                        choices=["sub", "dub", "ar_sub"])
    parser.add_argument("--timeout", type=float, default=40.0)
    args = parser.parse_args()

    try:
        from ani_cli_arabic.scrapers.provider_manager import ProviderManager
        import asyncio

        pm = ProviderManager()

        async def run():
            return await pm.resolve_stream(
                args.title, args.episode,
                mode="sub" if args.category == "sub" else
                     ("dub" if args.category == "dub" else "sub"),
                language="english",
                provider="auto",
                quiet=True,
            )

        url, headers, provider = asyncio.run(run())
    except Exception as exc:  # never emit a traceback to the JSON channel
        print(json.dumps({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "sources": [],
        }))
        return 1

    if not url:
        print(json.dumps({
            "ok": False,
            "error": "no stream resolved by provider chain",
            "sources": [],
        }))
        return 1

    print(json.dumps({
        "ok": True,
        "provider": provider or "",
        "sources": [{
            "server": (provider or "primary").lower(),
            "url": url,
            "quality": "auto",
            "headers": headers or {},
        }],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
