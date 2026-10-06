# Startet den Shop lokal. Aufruf: start.cmd   (anderer Port: start.cmd -Port 8001)
param([int]$Port = 8000)

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Zuerst setup.cmd ausfuehren." -ForegroundColor Red; exit 1 }
Set-Location (Join-Path $PSScriptRoot "core\server")
$env:PORT = "$Port"
Write-Host "Shop: http://localhost:$Port   Admin: http://localhost:$Port/admin/   Beenden: Strg+C" -ForegroundColor Green
& $py app.py
