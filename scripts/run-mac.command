#!/bin/bash
# jts-youtube-transcript — double-click launcher (macOS / Linux).
# Installs uv on first run if needed, then runs the tool via `uv run`,
# which handles the Python environment and dependencies automatically —
# nothing to set up by hand.

cd "$(dirname "$0")/.." || exit 1

if ! command -v uv >/dev/null 2>&1; then
  echo "First run: installing uv (a fast Python package/dependency manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "JTS YouTube Transcript"
echo "-----------------------"
read -r -p "YouTube URL: " URL

if [ -z "$URL" ]; then
  echo "No URL entered."
  read -r -p "Press Enter to close..."
  exit 1
fi

COOKIE_ARGS=()
read -r -p "Members-only video, or does it need your YouTube login? (y/N): " MEMBERS
if [[ "$MEMBERS" =~ ^[Yy]$ ]]; then
  read -r -p "Which browser are you logged into YouTube with? (chrome/safari/firefox) [chrome]: " BROWSER
  BROWSER=${BROWSER:-chrome}
  COOKIE_ARGS=(--cookies-from-browser "$BROWSER")
fi

uv run jts-youtube-transcript "$URL" "${COOKIE_ARGS[@]}"
STATUS=$?

echo ""
if [ $STATUS -eq 0 ]; then
  echo "Done — see Masterclass Transcripts/ for the file."
else
  echo "Something went wrong (exit code $STATUS) — see the messages above."
fi

read -r -p "Press Enter to close..."
