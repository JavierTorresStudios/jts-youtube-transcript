# jts-youtube-transcript

Turn a YouTube video into a clean, Markdown-ready transcript — no summarizing, no AI restructuring, just the raw text with clean frontmatter.

Cascades through three sources, cheapest first:

1. **Human-uploaded captions** (fast, free, most accurate)
2. **YouTube auto-generated captions** (fast, free, decent)
3. **Local Whisper transcription** (works on any video, including ones with no captions at all — opt-in, see below)

Supports members-only / login-required videos by borrowing your logged-in browser session.

## Install & run (any OS)

The fastest path uses [`uv`](https://docs.astral.sh/uv/), a Python package manager that handles the virtual environment and dependencies for you — nothing to configure by hand.

```bash
# one-time: install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
# or on Windows (PowerShell):
irm https://astral.sh/uv/install.ps1 | iex
```

Then, from a clone of this repo:

```bash
uv run jts-youtube-transcript "https://youtu.be/XXXXXXXXXXX"
```

That's it — `uv` creates an isolated environment, installs `yt-dlp`, and runs the tool. The transcript lands in a `Masterclass Transcripts/` folder created in whatever directory you ran the command from.

### Double-click launchers

If you'd rather not touch a terminal:

- **macOS / Linux:** double-click `scripts/run-mac.command` (or `scripts/run-linux.sh`)
- **Windows:** double-click `scripts/run-windows.bat`

Each one installs `uv` on first run if it's missing, prompts you for a URL, and asks whether the video needs your YouTube login.

### Alternative: pipx / pip

```bash
pipx install .
jts-youtube-transcript "https://youtu.be/XXXXXXXXXXX"
```

or plain pip inside your own virtualenv: `pip install .`

## Requirements

- Python 3.9+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) — installed automatically as a dependency
- `ffmpeg` on your `PATH` — install separately:
  - macOS: `brew install ffmpeg`
  - Windows: `winget install ffmpeg` (or see [ffmpeg.org](https://ffmpeg.org/download.html))
  - Linux: `apt install ffmpeg` / your distro's package manager

## Usage

```bash
# Simple — try captions, fall back to Whisper automatically
jts-youtube-transcript "https://youtu.be/XXXX"

# Members-only video — borrow your Chrome YouTube login
jts-youtube-transcript "https://youtu.be/XXXX" --cookies-from-browser chrome

# Force a specific caption source only
jts-youtube-transcript "https://youtu.be/XXXX" --source uploaded
jts-youtube-transcript "https://youtu.be/XXXX" --source auto-captions

# Force Whisper, with a specific model size
jts-youtube-transcript "https://youtu.be/XXXX" --source whisper --model medium

# Smoke-test the whole pipeline in under a minute
jts-youtube-transcript "https://youtu.be/XXXX" --sample 60

# Write somewhere other than ./Masterclass Transcripts
jts-youtube-transcript "https://youtu.be/XXXX" --output-dir ~/Transcripts
```

Run `jts-youtube-transcript --help` for the full option list.

## Whisper fallback (optional)

Whisper (via `faster-whisper`) is only needed for videos with **no captions at all** — rare, but it happens. It's an opt-in extra so the default install stays light:

```bash
uv run --extra whisper jts-youtube-transcript "https://youtu.be/XXXX"
# or
pip install "jts-youtube-transcript[whisper]"
```

If a caption-less video is passed without this installed, the tool tells you exactly what to run — it won't fail silently or nag you on every run.

## Output

A Markdown file with YAML frontmatter (title, channel, URL, date pulled, duration, and which source produced the transcript), written into `Masterclass Transcripts/`.

## Design philosophy

This tool is **transcription only** — it deliberately does not summarize, chapter, or restructure anything. The idea is that raw transcript beats an AI's first pass at "what it means"; synthesis is a separate, deliberate step you do afterward, with whatever lens you choose (recap, pull ideas, pressure-test, etc.) — not baked into the tool itself.

## License

MIT — see [LICENSE](LICENSE).
