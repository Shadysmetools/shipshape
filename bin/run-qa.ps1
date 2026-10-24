# One command QA (Windows). "demo" serves the bundled example app on 127.0.0.1:8765 and runs the full pipeline on it.
# Usage: powershell -File bin\run-qa.ps1 demo
#        powershell -File bin\run-qa.ps1 "<goal>" --plan plans\x.json --config qa.config.yaml --url http://127.0.0.1:8000/ --allow-host 127.0.0.1
$Root = Split-Path -Parent $PSScriptRoot
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command python3).Source }

function Stop-Tree($ProcessId) {
  # Kill the process and everything it spawned (python -m http.server may fork a child on some setups)
  try { Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Tree $_.ProcessId } } catch {}
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if ($args.Count -gt 0 -and $args[0] -eq 'demo') {
  $rest = @($args | Select-Object -Skip 1)
  $port = 8765
  $busy = $null
  try { $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue } catch {}
  if (-not $busy) { try { $busy = (netstat -ano | Select-String ":$port\s+.*LISTENING") } catch {} }
  if ($busy) {
    Write-Host "Port $port is already in use. Stop whatever listens there (an earlier demo server?) and run again."
    Write-Host "Find it with:  netstat -ano | findstr :$port   then  taskkill /PID <pid> /T /F"
    exit 3
  }
  $server = Start-Process -FilePath $Py -ArgumentList '-m', 'http.server', "$port", '--bind', '127.0.0.1', '--directory', ('"' + (Join-Path $Root 'examples\demo-app') + '"') -PassThru -WindowStyle Hidden
  try {
    Start-Sleep -Seconds 1
    & $Py (Join-Path $Root 'scripts\full_qa.py') 'Demo shop sign-up works' --plan (Join-Path $Root 'examples\demo-app\plans\signup.json') `
      --config (Join-Path $Root 'examples\demo-app\qa.config.yaml') --url "http://127.0.0.1:$port/" --allow-host 127.0.0.1 `
      --load smoke --load-scale 0.5 --repo (Join-Path $Root 'examples') --narrate @rest
    $code = $LASTEXITCODE
  } finally {
    Stop-Tree $server.Id
    Start-Sleep -Milliseconds 500
    $still = $null
    try { $still = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue } catch {}
    if ($still) { Write-Host "Warning: something still listens on port $port after the demo; use taskkill /PID <pid> /T /F" }
    else { Write-Host "Demo server stopped (port $port free)." }
  }
  exit $code
} else {
  & $Py (Join-Path $Root 'scripts\full_qa.py') @args
  exit $LASTEXITCODE
}
