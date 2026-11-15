param([switch]$SkipDependencies, [switch]$SkipInfrastructure)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv/Scripts/python.exe)) { py -3.12 -m venv .venv }
if (-not (Test-Path .env)) {
    $localDatabasePassword = [Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24)).ToLowerInvariant()
    $example = Get-Content .env.example -Raw
    $example = $example.Replace('CHANGE_ME_DATABASE_PASSWORD', $localDatabasePassword)
    Set-Content -LiteralPath .env -Value $example -Encoding utf8
    Write-Host 'Created ignored .env with a random local database password.'
}
if (-not $SkipDependencies) {
    & ./.venv/Scripts/python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }
    npm.cmd ci
    if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' }
}
if (-not $SkipInfrastructure) {
    docker compose up -d --wait
    if ($LASTEXITCODE) { throw 'Start Docker Desktop, then retry setup.' }
}
& ./.venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE) { throw 'Database migration failed.' }
Write-Host 'Create an owner credential with: .\.venv\Scripts\python.exe -m scripts.memoria bootstrap'
Write-Host 'Then run .\scripts\start.ps1. Ollama models must already be installed.'
