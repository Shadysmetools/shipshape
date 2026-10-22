#!/usr/bin/env bash
# One command QA. "demo" serves the bundled example app on 127.0.0.1:8765 and runs the full pipeline on it.
# Usage: bash bin/run-qa.sh demo
#        bash bin/run-qa.sh "<goal>" --plan plans/x.json --config qa.config.yaml --url http://127.0.0.1:8000/ --allow-host 127.0.0.1 [--send]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || command -v python)"
if [ "${1:-}" = "demo" ]; then
  shift
  "$PY" -m http.server 8765 --bind 127.0.0.1 --directory "$ROOT/examples/demo-app" >/dev/null 2>&1 &
  SERVER=$!; trap 'kill $SERVER 2>/dev/null' EXIT; sleep 1
  "$PY" "$ROOT/scripts/full_qa.py" "Demo shop sign-up works" --plan "$ROOT/examples/demo-app/plans/signup.json" \
    --config "$ROOT/examples/demo-app/qa.config.yaml" --url http://127.0.0.1:8765/ --allow-host 127.0.0.1 \
    --load smoke --load-scale 0.5 --repo "$ROOT/examples" --narrate "$@"
else
  "$PY" "$ROOT/scripts/full_qa.py" "$@"
fi
