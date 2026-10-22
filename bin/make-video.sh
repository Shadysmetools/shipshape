#!/usr/bin/env bash
# Make a video. Usage: bash bin/make-video.sh tutorial | bash bin/make-video.sh <scenes.json> <out.mp4>
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || command -v python)"
if [ "${1:-}" = "tutorial" ]; then shift; exec "$PY" "$ROOT/docs/media/tutorial/make_tutorial.py" "$@"; fi
exec "$PY" "$ROOT/scripts/slides_video.py" "$1" --out "$2"
