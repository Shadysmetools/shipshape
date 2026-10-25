#!/usr/bin/env bash
# ShipShape installer (macOS / Linux / Git Bash on Windows). Idempotent; no admin rights for the Python/npm parts.
# Usage: bash bin/install.sh [--with-desktop] [--with-k6] [--with-security] [--with-browsers]
# Downloads on a first install: Chromium about 150 MB (plus Firefox and WebKit, about 250 MB more, only with --with-browsers).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || command -v python || true)"
say() { printf '\n== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
to() { local s="$1"; shift; if have timeout; then timeout "$s" "$@"; elif have gtimeout; then gtimeout "$s" "$@"; else "$@"; fi; }  # macOS has no GNU timeout
WITH_DESKTOP=0; WITH_K6=0; WITH_SEC=0; WITH_BROWSERS=0
for a in "$@"; do case "$a" in --with-desktop) WITH_DESKTOP=1;; --with-k6) WITH_K6=1;; --with-security) WITH_SEC=1;; --with-browsers) WITH_BROWSERS=1;; esac; done

pm_install() {  # best effort with the platform package manager; prints the manual fix otherwise
  local pkg="$1"
  if have brew; then brew install "$pkg"
  elif have winget; then winget install --silent --accept-package-agreements --accept-source-agreements "$2"
  elif have apt-get; then sudo apt-get install -y "$pkg"
  else echo "Please install $pkg manually"; return 1; fi
}

say "Python"
[ -n "$PY" ] || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
"$PY" --version

say "Node.js (for the Playwright and Chrome DevTools MCP servers)"
have node || pm_install node OpenJS.NodeJS.LTS || true
have node && node --version

say "ffmpeg (video, narration mixing, screen recording)"
have ffmpeg || pm_install ffmpeg Gyan.FFmpeg || true
have ffmpeg && ffmpeg -version | head -1

say "Python packages"
if ! "$PY" -m pip install --user -r "$ROOT/requirements.txt"; then
  # Homebrew / Debian Python refuses --user installs (PEP 668): use a private venv instead
  "$PY" -m venv "$HOME/.shipshape/venv" && PY="$HOME/.shipshape/venv/bin/python" && "$PY" -m pip install -r "$ROOT/requirements.txt"
  echo "Installed into $HOME/.shipshape/venv. Put $HOME/.shipshape/venv/bin first on PATH before starting Claude Code,"
  echo "so the kit's 'python' commands use it:  export PATH=\"$HOME/.shipshape/venv/bin:\$PATH\""
fi
if [ "$WITH_DESKTOP" = 1 ]; then
  "$PY" -m pip install pyautogui mss pillow keyring
  case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) "$PY" -m pip install pywinauto ;; esac
fi
if [ "$WITH_SEC" = 1 ]; then "$PY" -m pip install pip-audit; fi

say "Playwright browser: Chromium (about 150 MB on a first install; already present = nothing to download)"
"$PY" -m playwright install chromium
if [ "$WITH_BROWSERS" = 1 ]; then
  say "Firefox and WebKit (about 250 MB, for cross-browser runs)"
  "$PY" -m playwright install firefox webkit
else
  echo "Skipping Firefox and WebKit: add --with-browsers for cross-browser runs."
fi

say "MCP servers (pinned; npx caches them)"
if have npx; then
  to 300 npx -y @playwright/mcp@0.0.83 --version || true
  to 300 npx -y chrome-devtools-mcp@1.10.1 --version || true
  to 300 npx -y playwright@1.59.1 --version || true   # the CLI behind "npx playwright show-trace"
fi

if [ "$WITH_K6" = 1 ]; then have k6 || pm_install k6 k6.k6 || true; fi
if [ "$WITH_SEC" = 1 ]; then have gitleaks || pm_install gitleaks Gitleaks.Gitleaks || true; fi

say "Doctor"
"$PY" "$ROOT/scripts/doctor.py" || true
echo
echo "Next: in Claude Code run  /plugin marketplace add Shadysmetools/shipshape  then  /plugin install smetools-agent-kit@shipshape"
echo "Or try the demo now:      bash $ROOT/bin/run-qa.sh demo"
