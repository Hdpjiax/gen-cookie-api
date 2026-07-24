$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$port = if ($env:API_PORT) { [int]$env:API_PORT } else { 8000 }
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if ($listener) {
    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    Write-Host "La API ya parece estar corriendo en http://127.0.0.1:$port"
    if ($process) {
        Write-Host "Proceso: $($process.ProcessName) PID $($process.Id)"
    }
    Write-Host "Para usar otro puerto: `$env:API_PORT=8001; .\scripts\start_api.ps1"
    exit 0
}

python -m uvicorn app.main:app --host 127.0.0.1 --port $port --reload
