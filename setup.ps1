# Richtet das Projekt auf einem Rechner ein (mehrfach ausfuehrbar):
#   Python-Umgebung .venv, Pakete, Update-Quelle "bauplan", lokaler Admin-Zugang, Tests.
# Aufruf: setup.cmd   (oder: powershell -ExecutionPolicy Bypass -File setup.ps1 [-OhneAdmin])
param([switch]$OhneAdmin)

$Bauplan = "https://github.com/xyztommixyz/shop-bauplan.git"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Fail($msg) { Write-Host "FEHLER: $msg" -ForegroundColor Red; exit 1 }

# 1) Python-Umgebung
if (-not (Test-Path $py)) {
    Write-Host "Python-Umgebung .venv anlegen ..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) { Fail "Python nicht gefunden. Python 3.13 installieren (python.org oder Microsoft Store)." }
}

# 2) Pakete
Write-Host "Pakete installieren ..."
& $py -m pip install -q --disable-pip-version-check -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { Fail "Pakete konnten nicht installiert werden." }

# 3) Update-Quelle "bauplan" (nur in Shop-Projekten, nicht im Bauplan selbst)
$origin = (git remote get-url origin) 2>$null
$remotes = @(git remote)
if ($origin -notmatch "shop-bauplan" -and $remotes -notcontains "bauplan") {
    git remote add bauplan $Bauplan
    Write-Host "Update-Quelle 'bauplan' eingetragen."
}

# 4) lokaler Admin-Zugang (nur wenn es noch keinen gibt)
if (-not $OhneAdmin) {
    Push-Location (Join-Path $PSScriptRoot "core\server")
    $admins = @(& $py app.py list-admins | Where-Object { $_ -and $_ -notmatch '^\[' })
    if ($admins.Count -eq 0) {
        Write-Host ""
        Write-Host "Noch kein Admin-Zugang. Lokalen Zugang 'Lokal' anlegen (Passwort mindestens 10 Zeichen):"
        & $py app.py set-admin Lokal
    } else {
        Write-Host "Admin-Zugaenge vorhanden: $($admins.Count)"
    }
    Pop-Location
}

# 5) Tests
Write-Host "Tests ..."
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Tests fehlgeschlagen (siehe oben)." }
Write-Host ""
Write-Host "Fertig. Shop starten mit: start.cmd" -ForegroundColor Green
