# Startet den Shop lokal. Aufruf: start.cmd   (anderer Port: start.cmd -Port 8001)
param([int]$Port = 8000)

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Zuerst setup.cmd ausfuehren." -ForegroundColor Red; exit 1 }
Set-Location (Join-Path $PSScriptRoot "core\server")
$env:PORT = "$Port"
# Links in Mails auf diesen Port zeigen lassen, sofern .env keine eigene Adresse (BASE_URL) vorgibt
$envFile = Join-Path (Get-Location) ".env"
if (-not $env:BASE_URL -and -not ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*BASE_URL=' -Quiet))) {
    $env:BASE_URL = "http://localhost:$Port"
}
Write-Host "Shop: http://localhost:$Port   Admin: http://localhost:$Port/admin/   Beenden: Strg+C" -ForegroundColor Green
& $py app.py
