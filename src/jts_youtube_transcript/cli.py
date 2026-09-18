#!/usr/bin/env python3
"""
jts-youtube-transcript.py

Turn a YouTube video into a clean, Obsidian-ready Markdown transcript.

Cascades through three sources, cheapest first:
  1. Human-uploaded captions   (fast, free, most accurate)
  2. YouTube auto-captions     (fast, free, decent)
  3. Local Whisper transcription (faster-whisper) — works on ANY video,
     including ones with no captions at all.

Supports authenticated (members-only / login-required) videos via
--cookies-from-browser, which borrows your logged-in browser session.

Requires on PATH: yt-dlp, ffmpeg
Requires (pip):    faster-whisper   (only imported if the whisper path runs)

Usage:
    python3 jts-youtube-transcript.py "https://www.youtube.com/watch?v=..." [options]

Examples:
    # Simple — try captions, fall back to whisper automatically
    python3 jts-youtube-transcript.py "https://youtu.be/XXXX"

    # Members-only video — borrow your Chrome YouTube login
    python3 jts-youtube-transcript.py "https://youtu.be/XXXX" --cookies-from-browser chrome

    # Force whisper, use a bigger/more accurate model
    python3 jts-youtube-transcript.py "https://youtu.be/XXXX" --source whisper --model medium

    # Smoke-test the whole pipeline in under a minute
    python3 jts-youtube-transcript.py "https://youtu.be/XXXX" --sample

Output:
    Writes a Markdown file with YAML frontmatter (title, channel, url,
    date pulled, duration, which source produced it) into the output
    directory. Default output directory is a "Masterclass Transcripts"
    folder created next to this script — so copying this one file into
    a different vault automatically gives that vault its own transcript
    folder too, with nothing to reconfigure.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]

# Rough, conservative CPU speed guidance. faster-whisper (int8) is
# typically several times faster than plain openai-whisper on the same
# hardware, but exact speed depends on the machine — treat these as a
# floor, not a promise.
WHISPER_SPEED_NOTES = {
    "tiny": "fastest, roughest — good for a quick skim",
    "base": "fast, rough draft quality",
    "small": "default — solid balance of speed and accuracy",
    "medium": "noticeably better, noticeably slower",
    "large": "best accuracy, slowest — save for videos that matter most",
}

EXIT_OK = 0
EXIT_BAD_USAGE = 2
EXIT_MISSING_DEP = 3
EXIT_DOWNLOAD_FAILED = 4
EXIT_NO_CAPTIONS = 5
EXIT_WHISPER_FAILED = 6
EXIT_OUTPUT_FAILED = 7
EXIT_INTERRUPTED = 130

AUTH_HINTS = ("members", "join this channel", "sign in", "private video", "this video is private")


class ToolError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def log(msg, quiet=False):
    if not quiet:
        print(msg, file=sys.stderr)


def die(msg, code):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def check_dependency(name):
    if shutil.which(name) is None:
        die(
            f"required tool '{name}' not found on PATH. "
            f"Install it with Homebrew: brew install {name}",
            EXIT_MISSING_DEP,
        )


def validate_url(url):
    if not url or "\\" in url:
        die(
            "URL is empty or shell-mangled (contains a backslash). "
            "Wrap the URL in single quotes when pasting into Terminal, "
            "e.g. 'https://youtu.be/XXXX'.",
            EXIT_BAD_USAGE,
        )
    if not re.search(r"(youtube\.com|youtu\.be)", url):
        die(f"'{url}' doesn't look like a YouTube URL.", EXIT_BAD_USAGE)


def run(cmd, quiet=False, verbose=False):
    """Run a subprocess, streaming output unless quiet. Returns (returncode, stdout, stderr)."""
    if verbose:
        log(f"[cmd] {' '.join(cmd)}", quiet=False)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if verbose and proc.stdout:
        print(proc.stdout, file=sys.stderr)
    if verbose and proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode, proc.stdout, proc.stderr


def tail(text, n=20):
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


def looks_like_auth_error(stderr_text):
    low = stderr_text.lower()
    return any(hint in low for hint in AUTH_HINTS)


def cookie_args(browser):
    return ["--cookies-from-browser", browser] if browser else []


def fetch_metadata(url, cookies, quiet, verbose):
    cmd = ["yt-dlp", "--dump-single-json", "--no-warnings", "--skip-download"]
    cmd += cookie_args(cookies)
    cmd += [url]
    code, out, err = run(cmd, quiet=quiet, verbose=verbose)
    if code != 0:
        if looks_like_auth_error(err):
            raise ToolError(
                "This video requires authentication (members-only or private). "
                "Re-run with --cookies-from-browser chrome (or safari/firefox), "
                "using a browser where you're logged into an account with access.",
                EXIT_DOWNLOAD_FAILED,
            )
        raise ToolError(f"couldn't read video metadata.\n{tail(err)}", EXIT_DOWNLOAD_FAILED)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise ToolError("yt-dlp returned metadata that wasn't valid JSON.", EXIT_DOWNLOAD_FAILED)


# ---------------------------------------------------------------------------
# Captions path
# ---------------------------------------------------------------------------

def collapse_rolling_captions(cues):
    """YouTube auto-captions emit a rolling window — each cue repeats the
    previous line plus a few new words. Collapse that back into clean,
    non-repeating text by finding the overlap between what we've already
    emitted and the start of the next cue."""
    words_out = []
    for cue in cues:
        words = cue.split()
        if not words:
            continue
        if not words_out:
            words_out.extend(words)
            continue
        max_overlap = min(len(words_out), len(words))
        overlap = 0
        for k in range(max_overlap, 0, -1):
            if words_out[-k:] == words[:k]:
                overlap = k
                break
        words_out.extend(words[overlap:])
    return " ".join(words_out)


def parse_vtt(path):
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    cues, buffer = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if buffer:
                cues.append(" ".join(buffer))
                buffer = []
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            buffer.append(clean)
    if buffer:
        cues.append(" ".join(buffer))
    return cues


def try_captions(url, tmpdir, lang, auto, cookies, sample_seconds, quiet, verbose):
    flag = "--write-auto-subs" if auto else "--write-subs"
    out_template = str(Path(tmpdir) / "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp", "--skip-download", flag,
        "--sub-langs", lang, "--convert-subs", "vtt",
        "--no-warnings", "-o", out_template,
    ]
    cmd += cookie_args(cookies)
    cmd += [url]
    code, _, err = run(cmd, quiet=quiet, verbose=verbose)
    if code != 0:
        if looks_like_auth_error(err):
            raise ToolError(
                "This video requires authentication (members-only or private). "
                "Re-run with --cookies-from-browser chrome (or safari/firefox).",
                EXIT_DOWNLOAD_FAILED,
            )
        return None  # no captions of this kind — fall through, not fatal

    vtt_files = list(Path(tmpdir).glob(f"*.{lang}.vtt"))
    if not vtt_files:
        return None

    cues = parse_vtt(vtt_files[0])
    if not cues:
        return None

    text = collapse_rolling_captions(cues)
    if sample_seconds:
        # Cheap approximation: trim to roughly the requested word budget
        # (~2.5 words/sec of natural speech) since we don't keep cue timings.
        words = text.split()
        budget = int(sample_seconds * 2.5)
        text = " ".join(words[:budget])
    return text


# ---------------------------------------------------------------------------
# Whisper path
# ---------------------------------------------------------------------------

def estimate_whisper_seconds(duration, model):
    # Conservative CPU ranges for faster-whisper (int8). Real hardware is
    # usually faster than the slow end of these ranges.
    ranges = {
        "tiny": (0.10, 0.20),
        "base": (0.15, 0.30),
        "small": (0.25, 0.50),
        "medium": (0.50, 1.00),
        "large": (1.00, 2.00),
    }
    lo, hi = ranges.get(model, (0.25, 0.50))
    return int(duration * lo), int(duration * hi)


def fmt_hms(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def download_audio(url, tmpdir, cookies, sample_seconds, quiet, verbose):
    out_template = str(Path(tmpdir) / "audio.%(ext)s")
    cmd = ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3", "--no-warnings", "-o", out_template]
    if sample_seconds:
        cmd += ["--download-sections", f"*0-{sample_seconds}"]
    cmd += cookie_args(cookies)
    cmd += [url]
    code, _, err = run(cmd, quiet=quiet, verbose=verbose)
    if code != 0:
        if looks_like_auth_error(err):
            raise ToolError(
                "This video requires authentication (members-only or private). "
                "Re-run with --cookies-from-browser chrome (or safari/firefox).",
                EXIT_DOWNLOAD_FAILED,
            )
        raise ToolError(
            f"yt-dlp failed to download audio. Common causes: invalid URL, "
            f"region block, or an outdated yt-dlp (try `brew upgrade yt-dlp`).\n{tail(err)}",
            EXIT_DOWNLOAD_FAILED,
        )
    audio_files = list(Path(tmpdir).glob("audio.*"))
    if not audio_files:
        raise ToolError("yt-dlp reported success but no audio file was found.", EXIT_DOWNLOAD_FAILED)
    return audio_files[0]


def transcribe_whisper(audio_path, model_size, lang, quiet, verbose):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die(
            "faster-whisper isn't installed. Install it with: pip3 install faster-whisper",
            EXIT_MISSING_DEP,
        )
    log(f"[whisper] loading model={model_size} ...", quiet)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    log(f"[whisper] transcribing ...", quiet)
    segments, info = model.transcribe(str(audio_path), language=lang or None)
    parts = []
    for seg in segments:
        parts.append(seg.text.strip())
        if verbose:
            print(f"[{fmt_hms(seg.start)} --> {fmt_hms(seg.end)}] {seg.text.strip()}", file=sys.stderr)
    text = " ".join(p for p in parts if p)
    if not text.strip():
        raise ToolError("whisper produced an empty transcript.", EXIT_WHISPER_FAILED)
    return text


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def slugify(title, video_id, max_len=80):
    slug = re.sub(r"[^\w\s-]", "", title).strip()
    slug = re.sub(r"[\s_-]+", " ", slug).strip()
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit(" ", 1)[0]
    return f"{slug} [{video_id}]" if slug else video_id


def write_markdown(out_dir, meta, transcript, source, model, sample_seconds):
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = slugify(meta.get("title") or meta.get("id"), meta.get("id")) + ".md"
    path = out_dir / filename

    fm = textwrap.dedent(f"""\
        ---
        title: "{(meta.get('title') or '').replace('"', "'")}"
        channel: "{(meta.get('uploader') or meta.get('channel') or '').replace('"', "'")}"
        url: {meta.get('webpage_url', '')}
        video_id: {meta.get('id', '')}
        duration_seconds: {meta.get('duration', 'null')}
        transcribed: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
        source: {source}
        whisper_model: {model if source == 'whisper' else 'null'}
        sample: {"true" if sample_seconds else "false"}
        ---
        """)

    body = f"# {meta.get('title', meta.get('id'))}\n\n{transcript.strip()}\n"

    try:
        path.write_text(fm + "\n" + body, encoding="utf-8")
    except OSError as e:
        raise ToolError(f"couldn't write output file: {e}", EXIT_OUTPUT_FAILED)

    return path, len(transcript)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="jts-youtube-transcript",
        description="Turn a YouTube video into a clean, Obsidian-ready Markdown transcript.",
    )
    p.add_argument("url", nargs="?", help="YouTube video URL")
    p.add_argument("--source", choices=["auto", "uploaded", "auto-captions", "whisper"], default="auto")
    p.add_argument("--lang", default="en", help="Caption language code (default: en)")
    p.add_argument("--model", choices=WHISPER_MODELS, default="small", help="Whisper model size (default: small)")
    p.add_argument("--cookies-from-browser", metavar="BROWSER", default=None,
                    help="Borrow login cookies from this browser (chrome, safari, firefox, edge) "
                         "for members-only/private videos.")
    p.add_argument("-o", "--output-dir", default=None,
                    help="Directory to write the transcript into "
                         "(default: 'Masterclass Transcripts' next to this script)")
    p.add_argument("--sample", nargs="?", const=60, type=int, metavar="SECONDS",
                    help="Smoke-test mode: only process the first SECONDS of the video (default 60)")
    p.add_argument("--keep-temp", action="store_true", help="Don't delete the working directory")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"jts-youtube-transcript {VERSION}")
    return p


def main():
    args = build_parser().parse_args()

    if not args.url:
        die("a YouTube URL is required. See --help.", EXIT_BAD_USAGE)
    validate_url(args.url)

    check_dependency("yt-dlp")
    check_dependency("ffmpeg")

    quiet, verbose = args.quiet, args.verbose
    cookies = args.cookies_from_browser

    out_dir = Path(args.output_dir) if args.output_dir else Path.cwd() / "Masterclass Transcripts"

    try:
        meta = fetch_metadata(args.url, cookies, quiet, verbose)
        duration = meta.get("duration") or 0
        log(f"[meta] \"{meta.get('title')}\" — {meta.get('uploader')} — {fmt_hms(duration)}", quiet)

        with tempfile.TemporaryDirectory() as tmpdir:
            transcript, source = None, None

            if args.source in ("auto", "uploaded"):
                log("[auto] trying uploaded captions ...", quiet)
                transcript = try_captions(args.url, tmpdir, args.lang, auto=False,
                                           cookies=cookies, sample_seconds=args.sample,
                                           quiet=quiet, verbose=verbose)
                if transcript:
                    source = "uploaded"

            if transcript is None and args.source in ("auto", "auto-captions"):
                log("[auto] trying auto-generated captions ...", quiet)
                transcript = try_captions(args.url, tmpdir, args.lang, auto=True,
                                           cookies=cookies, sample_seconds=args.sample,
                                           quiet=quiet, verbose=verbose)
                if transcript:
                    source = "auto-captions"

            if transcript is None and args.source in ("uploaded", "auto-captions"):
                die(f"no {args.source} captions found for lang='{args.lang}'.", EXIT_NO_CAPTIONS)

            if transcript is None and args.source in ("auto", "whisper"):
                log("[auto] no captions; falling back to whisper ..." if args.source == "auto"
                    else "[whisper] transcribing locally ...", quiet)
                if duration:
                    lo, hi = estimate_whisper_seconds(args.sample or duration, args.model)
                    log(f"[whisper-estimate] audio={fmt_hms(args.sample or duration)} "
                        f"model={args.model} est_range={fmt_hms(lo)}-{fmt_hms(hi)} "
                        f"({WHISPER_SPEED_NOTES[args.model]})", quiet)
                audio_path = download_audio(args.url, tmpdir, cookies, args.sample, quiet, verbose)
                transcript = transcribe_whisper(audio_path, args.model, args.lang if args.lang != "en" else None,
                                                 quiet, verbose)
                source = "whisper"

            if not transcript:
                raise ToolError(
                    "no transcript could be produced. If this is a members-only or private video, "
                    "re-run with --cookies-from-browser chrome (or safari/firefox).",
                    EXIT_DOWNLOAD_FAILED,
                )

            path, chars = write_markdown(out_dir, meta, transcript, source, args.model, args.sample)
            log(f"wrote {path} ({chars} chars, source={source})", quiet=False if not quiet else True)
            print(str(path))

    except ToolError as e:
        die(str(e), e.code)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(EXIT_INTERRUPTED)


if __name__ == "__main__":
    main()
