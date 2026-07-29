# Export FSD tables to JSONL by running the kit's worker inside the EVE client.
#
# The kit shells out to a standalone python27.exe, which the bundled runtime does
# not contain (it is stdlib only). The worker also needs the client's *Loader.pyd
# modules, so exefile.exe /py is the natural host.
$ErrorActionPreference = "Stop"

$here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$kit        = Join-Path $here "kit\EVE-New-Ship-Native-Authoring-Kit-build3396210"
$clientTq   = "C:\EVE-EVEJS\client\EVE\tq"
$binRoot    = Join-Path $clientTq "bin64"
$resFiles   = "C:\EVE-EVEJS\client\EVE\ResFiles"
$pythonHome = Join-Path $kit "runtime\python27"
$work       = Join-Path $here "fsd_work"
$exefile    = Join-Path $binRoot "exefile.exe"

$tasks = Get-Content -LiteralPath (Join-Path $work "tasks.json") -Raw | ConvertFrom-Json

$oldHome = $env:PYTHONHOME; $oldPath = $env:PYTHONPATH; $oldRes = $env:ELYSIAN_SHIPKIT_RESFILES
try {
    $env:PYTHONHOME = $pythonHome
    $env:PYTHONPATH = (Join-Path $pythonHome "Lib") + ";" + $binRoot
    $env:ELYSIAN_SHIPKIT_RESFILES = $resFiles
    foreach ($t in $tasks) {
        $name = $t[0]; $task = $t[1]; $result = $t[2]
        Remove-Item -LiteralPath $result -ErrorAction SilentlyContinue
        Write-Host "exporting $name ..."
        Push-Location $binRoot
        try { & $exefile /py (Join-Path $work "worker.py") $task $result /inherit } finally { Pop-Location }

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
Get-ChildItem (Join-Path $here "fsd_export") | ForEach-Object {
    "{0,-20} {1,12:N0} bytes" -f $_.Name, $_.Length
}
