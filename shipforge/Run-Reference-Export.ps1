# Export the client's dogma reference tables (read-only) using the client's own
# loaders. Same worker as the verification path; see export_reference.py.
$ErrorActionPreference = "Stop"

$here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools    = Split-Path -Parent $here
$kit      = Join-Path $tools "kit\EVE-New-Ship-Native-Authoring-Kit-build3396210"
$clientTq = "C:\EVE-EVEJS\client\EVE\tq"
$binRoot  = Join-Path $clientTq "bin64"
$work     = Join-Path $here "reference_work"
$exefile  = Join-Path $binRoot "exefile.exe"

$tasks = Get-Content -LiteralPath (Join-Path $work "tasks.json") -Raw | ConvertFrom-Json

$oldHome = $env:PYTHONHOME; $oldPath = $env:PYTHONPATH; $oldRes = $env:ELYSIAN_SHIPKIT_RESFILES
try {
    $env:PYTHONHOME = Join-Path $kit "runtime\python27"
    $env:PYTHONPATH = (Join-Path $kit "runtime\python27\Lib") + ";" + $binRoot
    $env:ELYSIAN_SHIPKIT_RESFILES = "C:\EVE-EVEJS\client\EVE\ResFiles"
    foreach ($t in $tasks) {
        $name = $t[0]; $task = $t[1]; $result = $t[2]
        Remove-Item -LiteralPath $result -ErrorAction SilentlyContinue
        Write-Host "exporting $name ..."
        Push-Location $binRoot
        try { & $exefile /py (Join-Path $tools "fsd_work\worker.py") $task $result /inherit } finally { Pop-Location }
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
