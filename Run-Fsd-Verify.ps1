# Export the LIVE (patched) FSD tables to fsd_verify, leaving the pristine
# fsd_export baseline untouched. Same worker as Run-Fsd-Export.ps1.
$ErrorActionPreference = "Stop"

$here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$kit        = Join-Path $here "kit\EVE-New-Ship-Native-Authoring-Kit-build3396210"
$clientTq   = "C:\EVE-EVEJS\client\EVE\tq"
$binRoot    = Join-Path $clientTq "bin64"
$pythonHome = Join-Path $kit "runtime\python27"
$work       = Join-Path $here "fsd_verify_work"
$exefile    = Join-Path $binRoot "exefile.exe"

$tasks = Get-Content -LiteralPath (Join-Path $work "tasks.json") -Raw | ConvertFrom-Json

$oldHome = $env:PYTHONHOME; $oldPath = $env:PYTHONPATH; $oldRes = $env:ELYSIAN_SHIPKIT_RESFILES
try {
    $env:PYTHONHOME = $pythonHome
    $env:PYTHONPATH = (Join-Path $pythonHome "Lib") + ";" + $binRoot
    $env:ELYSIAN_SHIPKIT_RESFILES = "C:\EVE-EVEJS\client\EVE\ResFiles"
    foreach ($t in $tasks) {
        $name = $t[0]; $task = $t[1]; $result = $t[2]
        Remove-Item -LiteralPath $result -ErrorAction SilentlyContinue
        Write-Host "exporting $name ..."
        Push-Location $binRoot
        try { & $exefile /py (Join-Path $here "fsd_work\worker.py") $task $result /inherit } finally { Pop-Location }
        $deadline = (Get-Date).AddSeconds(600)
        while (-not (Test-Path -LiteralPath $result)) {
            if ((Get-Date) -ge $deadline) { throw "$name timed out" }
            Start-Sleep -Milliseconds 300
        }
        $r = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
        if (-not $r.success) { Write-Host "  FAILED: $($r.error)" -ForegroundColor Red; exit 1 }
        Write-Host "  OK $name" -ForegroundColor Green
    }
} finally {
    $env:PYTHONHOME = $oldHome; $env:PYTHONPATH = $oldPath; $env:ELYSIAN_SHIPKIT_RESFILES = $oldRes
}
