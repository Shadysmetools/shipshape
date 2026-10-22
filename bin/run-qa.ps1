# One command QA (Windows). "demo" serves the bundled example app on 127.0.0.1:8765 and runs the full pipeline on it.
# Usage: powershell -File bin\run-qa.ps1 demo
#        powershell -File bin\run-qa.ps1 "<goal>" --plan plans\x.json --config qa.config.yaml --url http://127.0.0.1:8000/ --allow-host 127.0.0.1
$Root = Split-Path -Parent $PSScriptRoot
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command python3).Source }
if ($args.Count -gt 0 -and $args[0] -eq 'demo') {
  $rest = @($args | Select-Object -Skip 1)
  $server = Start-Process -FilePath $Py -ArgumentList '-m', 'http.server', '8765', '--bind', '127.0.0.1', '--directory', ('"' + (Join-Path $Root 'examples\demo-app') + '"') -PassThru -WindowStyle Hidden
  try {
    Start-Sleep -Seconds 1
    & $Py (Join-Path $Root 'scripts\full_qa.py') 'Demo shop sign-up works' --plan (Join-Path $Root 'examples\demo-app\plans\signup.json') `
      --config (Join-Path $Root 'examples\demo-app\qa.config.yaml') --url 'http://127.0.0.1:8765/' --allow-host 127.0.0.1 `
      --load smoke --load-scale 0.5 --repo (Join-Path $Root 'examples') --narrate @rest
  } finally { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
} else {
  & $Py (Join-Path $Root 'scripts\full_qa.py') @args
}
exit $LASTEXITCODE
