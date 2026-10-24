# ShipShape installer for Windows PowerShell 5.1+ / PowerShell 7. Idempotent; per-user installs (no admin) where possible.
# Usage: powershell -ExecutionPolicy Bypass -File bin\install.ps1 [-WithDesktop] [-WithK6] [-WithSecurity] [-WithBrowsers]
# Downloads on a first install: Chromium about 150 MB (plus Firefox and WebKit, about 250 MB more, only with -WithBrowsers).
param([switch]$WithDesktop, [switch]$WithK6, [switch]$WithSecurity, [switch]$WithBrowsers)
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
function Say($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function WingetInstall($id) {
  if (Have winget) { winget install --id $id --silent --accept-package-agreements --accept-source-agreements --scope user }
  else { Write-Host "Install $id manually (winget not found)" }
}

Say 'Python'
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { WingetInstall 'Python.Python.3.12'; $Py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Py) { Write-Host 'Python 3.10+ is required. Open a new terminal after installing it.'; exit 1 }
& $Py --version

Say 'Node.js (for the Playwright and Chrome DevTools MCP servers)'
if (-not (Have node)) { WingetInstall 'OpenJS.NodeJS.LTS' }
if (Have node) { node --version }

Say 'ffmpeg (video, narration mixing, screen recording)'
if (-not (Have ffmpeg)) { WingetInstall 'Gyan.FFmpeg' }
if (Have ffmpeg) { (ffmpeg -version | Select-Object -First 1) }

Say 'Python packages'
& $Py -m pip install --user -r (Join-Path $Root 'requirements.txt')
if ($WithDesktop) { & $Py -m pip install --user pyautogui pywinauto keyring }
if ($WithSecurity) { & $Py -m pip install --user pip-audit }

Say 'Playwright browser: Chromium (about 150 MB on a first install; already present = nothing to download)'
& $Py -m playwright install chromium
if ($WithBrowsers) { Say 'Firefox and WebKit (about 250 MB, for cross-browser runs)'; & $Py -m playwright install firefox webkit }
else { Write-Host 'Skipping Firefox and WebKit: add -WithBrowsers for cross-browser runs.' }

Say 'MCP servers (pinned; npx caches them)'
if (Have npx) {
  npx -y '@playwright/mcp@0.0.83' --version
  npx -y 'chrome-devtools-mcp@1.10.1' --version
  npx -y 'playwright@1.59.1' --version   # the CLI behind "npx playwright show-trace"
}
if ($WithK6 -and -not (Have k6)) { WingetInstall 'k6.k6' }
if ($WithSecurity -and -not (Have gitleaks)) { WingetInstall 'Gitleaks.Gitleaks' }

Say 'Doctor'
& $Py (Join-Path $Root 'scripts\doctor.py')
Write-Host "`nNext: in Claude Code run  /plugin marketplace add Shadysmetools/shipshape  then  /plugin install smetools-agent-kit@shipshape"
Write-Host "Or try the demo now:      powershell -File $Root\bin\run-qa.ps1 demo"
