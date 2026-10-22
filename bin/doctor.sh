#!/usr/bin/env bash
# ShipShape health check. Usage: bash bin/doctor.sh [--json]
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || command -v python)"
exec "$PY" "$ROOT/scripts/doctor.py" "$@"
