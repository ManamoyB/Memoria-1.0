$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .env)) { throw 'Run scripts/setup.ps1 first.' }
docker compose up -d --wait
if ($LASTEXITCODE) { throw 'Infrastructure failed to start.' }
& ./.venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE) { throw 'Database migration failed.' }
$pythonPath = (Resolve-Path .venv/Scripts/python.exe).Path
$workerProcess = Start-Process $pythonPath -ArgumentList '-m','scripts.memoria','worker' -PassThru -WindowStyle Hidden -RedirectStandardOutput 'storage/worker.log' -RedirectStandardError 'storage/worker-error.log'
$apiProcess = Start-Process $pythonPath -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -PassThru -WindowStyle Hidden -RedirectStandardOutput 'storage/api.log' -RedirectStandardError 'storage/api-error.log'
try {
    Write-Host 'MemoriaOS: http://localhost:3000 | API: http://localhost:8000/docs'
    npm.cmd run dev -- --host 127.0.0.1
} finally {
    foreach ($ownedProcess in @($workerProcess, $apiProcess)) {
        if (-not $ownedProcess.HasExited) { Stop-Process -Id $ownedProcess.Id }
    }
}
