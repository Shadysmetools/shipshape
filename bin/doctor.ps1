# ShipShape health check. Usage: powershell -File bin\doctor.ps1 [--json]
$Root = Split-Path -Parent $PSScriptRoot
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source; if (-not $Py) { $Py = (Get-Command python3).Source }
& $Py (Join-Path $Root "scripts\doctor.py") @args
exit $LASTEXITCODE
