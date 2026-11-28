#!/usr/bin/env bash
# Start the live-captions server and say which page to open.
# Usage: ./run.sh            (Ctrl-C to stop; recordings and transcripts are saved on the way out)
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (stand-in engines, no cloud). Add your API keys to .env for real captions."
fi

# Read a setting from .env (ignores comments); fall back to a default.
setting() {
  local v
  v=$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/[[:space:]]#.*//; s/^[[:space:]]*//; s/[[:space:]]*$//')
  echo "${v:-$2}"
}
PORT=$(setting PORT 8765)
HOST=$(setting HOST 127.0.0.1)
STT=$(setting STT_ENGINE stub)
TR=$(setting TRANSLATE_ENGINE stub)

if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  echo "Port $PORT is already in use: the server may already be running. Open http://localhost:$PORT/" >&2
  exit 1
fi

echo
echo "  live-captions — speech: $STT, translation: $TR"
echo
echo "  ▶ Open the control page in Chrome on THIS computer:"
echo "      http://localhost:$PORT/"
echo "    Pick the mixer input, press Start listening, paste the Zoom caption link if needed,"
echo "    then open the caption window from there."
if [ "$HOST" = "0.0.0.0" ]; then
  echo "    Other machines on the network can open the caption display; the control page shows the link."
fi
if [ "$STT" = "stub" ] || [ "$TR" = "stub" ]; then
  echo
  echo "  Note: stand-in engines are on (no real speech recognition or translation)."
  echo "        Set STT_ENGINE / TRANSLATE_ENGINE and the API keys in .env for the real thing."
fi
echo
echo "  Ctrl-C stops the server (the current recording and transcript are saved)."
echo

exec uv run python -m app
