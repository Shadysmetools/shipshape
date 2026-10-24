#!/usr/bin/env bash
# One command QA. "demo" serves the bundled example app on 127.0.0.1:8765 and runs the full pipeline on it.
# Usage: bash bin/run-qa.sh demo
#        bash bin/run-qa.sh "<goal>" --plan plans/x.json --config qa.config.yaml --url http://127.0.0.1:8000/ --allow-host 127.0.0.1 [--send]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || command -v python)"
PORT=8765

port_busy() {  # true when something already listens on $PORT (lsof on macOS, ss on Linux, netstat on Git Bash)
  if command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  elif command -v ss >/dev/null 2>&1; then ss -ltn 2>/dev/null | grep -q ":$PORT " && return 0
  elif command -v netstat >/dev/null 2>&1; then netstat -ano 2>/dev/null | grep -E ":$PORT +.*LISTEN" >/dev/null && return 0
  fi
  return 1
}

stop_tree() {  # the server and anything it spawned
  local pid="$1"
  if command -v pkill >/dev/null 2>&1; then pkill -P "$pid" 2>/dev/null || true; fi
  kill "$pid" 2>/dev/null || true
  case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) taskkill //PID "$pid" //T //F >/dev/null 2>&1 || true ;; esac
}

if [ "${1:-}" = "demo" ]; then
  shift
  if port_busy; then
    echo "Port $PORT is already in use. Stop whatever listens there (an earlier demo server?) and run again."
    exit 3
  fi
  "$PY" -m http.server "$PORT" --bind 127.0.0.1 --directory "$ROOT/examples/demo-app" >/dev/null 2>&1 &
  SERVER=$!
  trap 'stop_tree $SERVER' EXIT
  sleep 1
  set +e
  "$PY" "$ROOT/scripts/full_qa.py" "Demo shop sign-up works" --plan "$ROOT/examples/demo-app/plans/signup.json" \
    --config "$ROOT/examples/demo-app/qa.config.yaml" --url "http://127.0.0.1:$PORT/" --allow-host 127.0.0.1 \
    --load smoke --load-scale 0.5 --repo "$ROOT/examples" --narrate "$@"
  CODE=$?
  set -e
  exit $CODE
else
  exec "$PY" "$ROOT/scripts/full_qa.py" "$@"
fi
