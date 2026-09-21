<#
.SYNOPSIS
End-to-end VisionForge demo, from nothing: creates a venv, installs
dependencies, generates the synthetic test clip if it doesn't exist yet,
runs the full offline reconstruction pipeline (with --persist), starts the
read-only/persist API, and starts the frontend dev server pointed at it.

.EXAMPLE
.\scripts\run_demo.ps1
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$VenvDir = Join-Path $RepoRoot ".venv"
$Clip = Join-Path $RepoRoot "data\input\synthetic_box_room.mp4"
$RunDir = Join-Path $RepoRoot "outputs\demo"

Write-Host "== VisionForge end-to-end demo =="
Write-Host "Repo root: $RepoRoot"

if (-not (Test-Path $VenvDir)) {
    Write-Host "[1/6] Creating venv at $VenvDir..."
    python -m venv $VenvDir
} else {
    Write-Host "[1/6] Using existing venv at $VenvDir"
}

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PipExe = Join-Path $VenvDir "Scripts\pip.exe"

Write-Host "[2/6] Installing Python dependencies..."
& $PipExe install -q -r requirements.txt

if (-not (Test-Path $Clip)) {
    Write-Host "[3/6] Generating synthetic test clip at $Clip..."
    & $PythonExe scripts\generate_synthetic_clip.py --output $Clip
} else {
    Write-Host "[3/6] Synthetic clip already exists at $Clip (skipping generation)"
}

Write-Host "[4/6] Running the offline reconstruction pipeline"
Write-Host "      (real feature matching, real triangulation, real RANSAC plane fitting -- takes roughly 1-2 minutes)..."
$env:PYTHONPATH = Join-Path $RepoRoot "src"
& $PythonExe -m visionforge.cli reconstruct --video $Clip --output $RunDir --input-type synthetic --no-viewer --persist
if ($LASTEXITCODE -ne 0) { throw "visionforge reconstruct failed with exit code $LASTEXITCODE" }

Write-Host "[5/6] Starting the API server on http://localhost:8000 ..."
$ApiLog = Join-Path $RepoRoot ".demo_api.log"
$ApiErrLog = Join-Path $RepoRoot ".demo_api_err.log"
$ApiProcess = Start-Process -FilePath $PythonExe `
    -ArgumentList "-m", "uvicorn", "visionforge.api.app:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $ApiLog -RedirectStandardError $ApiErrLog
Write-Host "      API PID: $($ApiProcess.Id) (log: .demo_api.log)"
Start-Sleep -Seconds 2

Write-Host "[6/6] Installing frontend dependencies, building, and starting the dev server on http://localhost:5173 ..."
Set-Location (Join-Path $RepoRoot "frontend")
npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit code $LASTEXITCODE" }

$FrontendLog = Join-Path $RepoRoot ".demo_frontend.log"
$FrontendErrLog = Join-Path $RepoRoot ".demo_frontend_err.log"
$FrontendProcess = Start-Process -FilePath "npm" -ArgumentList "run", "dev", "--", "--port", "5173" `
    -WorkingDirectory (Join-Path $RepoRoot "frontend") -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErrLog
Write-Host "      Frontend PID: $($FrontendProcess.Id) (log: .demo_frontend.log)"

Set-Location $RepoRoot

Write-Host ""
Write-Host "Demo is running:"
Write-Host "  API:            http://localhost:8000"
Write-Host "  API docs:       http://localhost:8000/docs"
Write-Host "  Frontend:       http://localhost:5173"
Write-Host "  Persisted run:  $RunDir (session id: demo)"
Write-Host ""
Write-Host "Stop both servers with:"
Write-Host "  Stop-Process -Id $($ApiProcess.Id),$($FrontendProcess.Id)"
