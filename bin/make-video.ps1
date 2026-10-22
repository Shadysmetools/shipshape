# Make a video. Usage: powershell -File bin\make-video.ps1 tutorial | bin\make-video.ps1 <scenes.json> <out.mp4>
$Root = Split-Path -Parent $PSScriptRoot
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source; if (-not $Py) { $Py = (Get-Command python3).Source }
if ($args.Count -gt 0 -and $args[0] -eq "tutorial") { & $Py (Join-Path $Root "docs\media\tutorial\make_tutorial.py") @($args | Select-Object -Skip 1) }
else { & $Py (Join-Path $Root "scripts\slides_video.py") $args[0] --out $args[1] }
exit $LASTEXITCODE
