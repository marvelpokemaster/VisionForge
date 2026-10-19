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
# A dirty $RunDir from a previous run makes P1's visualization-file rename
# collide on Windows (os.rename fails if the destination already exists,
# unlike POSIX) -- clear it first so re-running this script is idempotent.
# Caught for real by literally re-running the bash equivalent during Task H.
if (Test-Path $RunDir) { Remove-Item -Recurse -Force $RunDir }
$env:PYTHONPATH = Join-Path $RepoRoot "src"
& $PythonExe -m visionforge.cli reconstruct --video $Clip --output $RunDir --input-type synthetic --no-viewer --persist
if ($LASTEXITCODE -ne 0) { throw "visionforge reconstruct failed with exit code $LASTEXITCODE" }

# `Start-Process -FilePath "npm"` on Windows launches npm.cmd, a wrapper
# that spawns node.exe as a CHILD process -- so $Process.Id is the wrapper's
# PID, not the actual dev-server process that ends up listening on the
# port. Look up the PID really bound to the port instead. Caught for real
# during Task H's clean-checkout verification (the bash equivalent of this
# script had the identical bug for both the API and the frontend).
function Find-PidByPort {
    param([int]$Port)
    for ($i = 0; $i -lt 15; $i++) {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { return $conn.OwningProcess }
        Start-Sleep -Seconds 1
    }
    return $null
}

Write-Host "[5/6] Starting the API server on http://localhost:8000 ..."
$ApiLog = Join-Path $RepoRoot ".demo_api.log"
$ApiErrLog = Join-Path $RepoRoot ".demo_api_err.log"
$ApiLauncher = Start-Process -FilePath $PythonExe `
    -ArgumentList "-m", "uvicorn", "visionforge.api.app:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $ApiLog -RedirectStandardError $ApiErrLog
$ApiPid = Find-PidByPort -Port 8000
if (-not $ApiPid) { $ApiPid = $ApiLauncher.Id }
Write-Host "      API listening (PID: $ApiPid, log: .demo_api.log)"

Write-Host "[6/6] Installing frontend dependencies, building, and starting the dev server on http://localhost:5173 ..."
Set-Location (Join-Path $RepoRoot "frontend")
npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit code $LASTEXITCODE" }

$FrontendLog = Join-Path $RepoRoot ".demo_frontend.log"
$FrontendErrLog = Join-Path $RepoRoot ".demo_frontend_err.log"
# Start-Process -FilePath "npm" fails outright on Windows ("%1 is not a
# valid Win32 application"): npm resolves to npm.cmd, and Start-Process's
# underlying CreateProcess call -- unlike PowerShell's own normal command
# invocation -- doesn't know how to run a .cmd file directly. Route it
# through cmd.exe /c instead. Caught for real running this script.
$FrontendLauncher = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm", "run", "dev", "--", "--port", "5173" `
    -WorkingDirectory (Join-Path $RepoRoot "frontend") -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErrLog
$FrontendPid = Find-PidByPort -Port 5173
if (-not $FrontendPid) { $FrontendPid = $FrontendLauncher.Id }
Write-Host "      Frontend listening (PID: $FrontendPid, log: .demo_frontend.log)"

Set-Location $RepoRoot

Write-Host ""
Write-Host "Demo is running:"
Write-Host "  API:            http://localhost:8000"
Write-Host "  API docs:       http://localhost:8000/docs"
Write-Host "  Frontend:       http://localhost:5173"
Write-Host "  Persisted run:  $RunDir (session id: demo)"
Write-Host ""
Write-Host "Stop both servers with:"
Write-Host "  Stop-Process -Id $ApiPid,$FrontendPid"
Write-Host ""
Write-Host "(If that doesn't work, find the real PID with: Get-NetTCPConnection -LocalPort 8000,5173 -State Listen)"
