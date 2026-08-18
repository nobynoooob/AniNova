<div align="center">

<h2>💖 Support This Open Source Project</h2>
<p>Your support helps maintain the project and keeps the updates coming!</p>
<a href="https://paypal.me/np4abdou">
  <img src="https://img.shields.io/badge/Donate_with_PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate with PayPal">
</a>
<br><br><br>

**AniNova — desktop anime streaming app with Arabic subtitles**

<p align="center">
  <a href="https://github.com/nobynoooob/AniNova/stargazers">
    <img src="https://img.shields.io/github/stars/nobynoooob/AniNova?style=for-the-badge" />
  </a>
  <a href="https://github.com/nobynoooob/AniNova/network">
    <img src="https://img.shields.io/github/forks/nobynoooob/AniNova?style=for-the-badge" />
  </a>
  <br>
  <a href="https://github.com/nobynoooob/AniNova/releases">
    <img src="https://img.shields.io/github/v/release/nobynoooob/AniNova?style=for-the-badge" />
  </a>
  <a href="https://github.com/nobynoooob/AniNova/releases">
    <img src="https://img.shields.io/badge/Windows-Linux-blue?style=for-the-badge" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/License-GPL--3.0-green?style=for-the-badge" />
</p>

<br>

</div>

---

## 📑 Navigation

[Installation](#-installation) • [Features](#-features) • [Getting Started](#-getting-started) • [Configuration](#%EF%B8%8F-configuration) • [Build & Release](#-build--release-for-maintainers) • [Contributors](#-contributors) • [License](#-license)

---

## 📦 Installation

Grab the latest release from the [releases page](https://github.com/nobynoooob/AniNova/releases):

| Asset | Platform | What's inside |
|-------|----------|---------------|
| `AniNova-v<version>-Linux.tar.gz` | Linux | Single-file executable + desktop entry + installer |
| `AniNova-v<version>-Windows-Portable.zip` | Windows | Portable folder (exe + DLLs + bundled mpv) |

### Requirements

- **Linux**: WebKit2GTK/GTK3 (the pywebview backend) and **mpv** or **VLC**.
  The packaged release is built against Ubuntu's WebKit2GTK 4.1 — on distros
  without it, install: `libwebkit2gtk-4.1-dev gir1.2-webkit2-4.1 python3-gi`
- **Windows**: WebView2 runtime (pre-installed on Windows 10/11). The portable
  release bundles **mpv**, so no extra media player is required.
- **Playwright Chromium**: downloaded automatically on the first stream
  resolution (not bundled — keeps downloads small).

### From Source (Development)

```bash
git clone https://github.com/nobynoooob/AniNova.git
cd AniNova
pip install -r requirements.txt     # or: pip install -e .
```

Launch it:

```bash
# Linux (auto-activates a local venv if present)
./launch.sh

# Windows
launch.bat

# or directly:
python -m ani_cli_arabic.gui          # --debug for devtools
ani-cli-ar-gui                        # after pip install
```

> **Linux note**: pywebview needs the GTK/WebKit2 stack — `sudo apt-get install
> libwebkit2gtk-4.1-dev gir1.2-webkit2-4.1 python3-gi python3-gi-cairo
> libgirepository-1.0-dev`.

---

## 🎯 Features

### Streaming & Playback
- **Multi-provider engine**: Miruro, HiAnime, AllAnime, API, Mkissa, and
  GogoAnime chained with per-step failure isolation — the first working source
  wins, and you can also **pick a specific provider**.
- **Arabic track**: dedicated Arabic API pipeline with **Arabic subtitle
  tracks** and quality selection (1080p/720p/480p/auto).
- **mpv / VLC playback** with buffer/caching flags for slow connections.
- **Provider resolution runs off the UI thread** with bounded timeouts and
  cancellation (abort/cancel events thread through the browser queue) — the
  interface never freezes.

### Discovery & Browsing
- **Search** across English and Japanese titles plus **Arabic** search.
- **Trending** and **Airing Schedule**.
- **Rich details**: synopsis, ratings, cover posters (AniList), metadata, and
  episode lists per provider.

### Personal Library
- **Continue Watching**: resume exactly where you left off (progress tracked).
- **My List (Bookmarks)**: save anime for quick access.

### Watch Together 🎬
- Host or join a **room** to watch synchronized with friends.
- Each participant picks **mpv or VLC** (unique IPC socket / rc host per player).
- Host controls seek/pause/play; state syncs via Supabase Realtime.

### Experience
- **PyWebView desktop window** (native WebView2 on Windows / WebKit on Linux)
  with a rich single-page UI.
- **Posters & art** rendered for every anime.
- **Automatic update checking**.
- **Anonymous usage analytics** (opt-out in settings).

---

## 🚀 Getting Started

1. **Search** for an anime (or use Trending / Schedule on the home screen).
2. Open an anime to see **episodes** across providers.
3. Pick an episode — AniNova auto-resolves a stream (or let you choose a provider).
4. Choose **quality** and hit play — mpv/VLC opens and streams.
5. For Arabic subtitles, use the **Arabic** tab/track.

---

## ⚙️ Configuration

Settings are stored locally in `~/.ani-cli-arabic/database/config.json`.

- **Default quality** and **media player** (mpv/VLC)
- **MPV aspect-ratio / player flags**
- **Analytics**: opt-in/out of anonymous usage stats (auto-enabled by default)
- **Update checking**: toggle automatic update notifications

---

## 🔧 Build & Release (for maintainers)

Build the desktop executable with `build_desktop.py`:

```bash
python build_desktop.py                         # one-file GUI executable
python build_desktop.py --onedir --bundle-mpv --zip   # portable folder + zip
python build_desktop.py --exclude-module unittest      # extra exclusions
```

- Windows builds use **--onedir + --bundle-mpv** to produce the portable zip.
- The Playwright **driver** is bundled (`--collect-all playwright`), but the
  Chromium **browser** is not — it downloads on first use.
- Releases are built automatically by `.github/workflows/build.yml` on `v*`
  tag pushes.

---

## 👥 Contributors

**Creator & Maintainer:**
- [@nobynoooob](https://github.com/nobynoooob) - Creator and maintainer

Want to contribute? Feel free to open issues or submit pull requests!

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0**.

You're free to use, modify, and distribute this software under the terms of the GPL-3.0 license. See the [LICENSE](LICENSE) file for the full legal text.

**In simple terms:**
- ✅ Use it for personal or commercial purposes
- ✅ Modify the source code
- ✅ Distribute it to others
- ⚠️ Any modifications must also be open source under GPL-3.0
- ⚠️ Include the original copyright notice

---

<div align="center">

### ⚠️ Important Notice

> [! CAUTION]
> **By using this software you understand:**
>
> - Anonymous usage statistics are collected for the GitHub page stats banner (can be disabled in settings)
> - The project is licensed under GPL-3.0 — see [LICENSE](LICENSE) for details
> - We do not host any content; all streams are from third-party sources
> - This tool is for personal use and educational purposes only

</div>

---

<br>

Made with ❤️ by the anime community

[⭐ Star this repo](https://github.com/nobynoooob/AniNova) | [🐛 Report bugs](https://github.com/nobynoooob/AniNova/issues) | [💬 Discussions](https://github.com/nobynoooob/AniNova/discussions)
