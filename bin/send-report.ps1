# Deliver a QA run to the channels in qa.config.yaml. Dry-run unless --send.
# Usage: powershell -File bin\send-report.ps1 qa-runs\<run> [--config qa.config.yaml] [--lang ar] [--send]
$Root = Split-Path -Parent $PSScriptRoot
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source; if (-not $Py) { $Py = (Get-Command python3).Source }
& $Py (Join-Path $Root "scripts\privacy.py") scan $args[0]
if ($LASTEXITCODE -ne 0) { Write-Host "Privacy scan found something: fix it before sending."; exit 1 }
& $Py (Join-Path $Root "scripts\notify.py") @args
exit $LASTEXITCODE
