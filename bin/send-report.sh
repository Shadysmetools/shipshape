#!/usr/bin/env bash
# Deliver a QA run to the channels in qa.config.yaml. Dry-run unless --send.
# Usage: bash bin/send-report.sh qa-runs/<run> [--config qa.config.yaml] [--lang ar] [--send]
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || command -v python)"
"$PY" "$ROOT/scripts/privacy.py" scan "$1" || { echo "Privacy scan found something: fix it before sending."; exit 1; }
exec "$PY" "$ROOT/scripts/notify.py" "$@"
