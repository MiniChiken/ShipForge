# Author the Venator hull natively inside the EVE client.
#
# Mirrors the Elysian kit's Invoke-NativeWorker: point PYTHONHOME at the bundled
# 2.7 runtime, point ELYSIAN_SHIPKIT_RESFILES at the client's ResFiles, run from
# the tq folder so resfileindex.txt is found in cwd, then hand the worker to
# exefile.exe /py.
#
# Writes ONLY under native_out/. The live client is not modified by this script.
$ErrorActionPreference = "Stop"

$here      = Split-Path -Parent $MyInvocation.MyCommand.Path
$kit       = Join-Path $here "kit\EVE-New-Ship-Native-Authoring-Kit-build3396210"
$clientTq  = "C:\EVE-EVEJS\client\EVE\tq"
$resFiles  = "C:\EVE-EVEJS\client\EVE\ResFiles"
$pythonHome= Join-Path $kit "runtime\python27"
$worker    = Join-Path $here "author_venator.py"
$request   = Join-Path $here "venator_request.json"
$outDir    = Join-Path $here "native_out"
$result    = Join-Path $outDir "venator-author-result.json"

New-Item -ItemType Directory -Path $outDir -Force | Out-Null
Remove-Item -LiteralPath $result -ErrorAction SilentlyContinue

$exefile = Join-Path $clientTq "bin64\exefile.exe"
if (-not (Test-Path -LiteralPath $exefile))    { throw "Missing $exefile" }
if (-not (Test-Path -LiteralPath $worker))     { throw "Missing $worker" }
if (-not (Test-Path -LiteralPath $request))    { throw "Missing $request" }
if (-not (Test-Path -LiteralPath (Join-Path $pythonHome "Lib\site.py"))) {
    throw "Python 2.7 runtime missing at $pythonHome"
}

$oldHome = $env:PYTHONHOME; $oldPath = $env:PYTHONPATH; $oldRes = $env:ELYSIAN_SHIPKIT_RESFILES
try {
    $env:PYTHONHOME = $pythonHome
    $env:PYTHONPATH = Join-Path $pythonHome "Lib"
    $env:ELYSIAN_SHIPKIT_RESFILES = $resFiles
    Push-Location $clientTq
    try { & $exefile /py $worker $result $request /inherit } finally { Pop-Location }

    $deadline = (Get-Date).AddSeconds(180)
    while (-not (Test-Path -LiteralPath $result)) {
        if ((Get-Date) -ge $deadline) { throw "Native worker timed out without writing $result" }
        Start-Sleep -Milliseconds 250
    }
} finally {
    $env:PYTHONHOME = $oldHome; $env:PYTHONPATH = $oldPath; $env:ELYSIAN_SHIPKIT_RESFILES = $oldRes
}

$r = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
if (-not $r.success) {
    Write-Host "AUTHORING FAILED" -ForegroundColor Red
    Write-Host $r.error
    exit 1
}
Write-Host "AUTHORING OK" -ForegroundColor Green
Write-Host ("  hull            : " + $r.authored.name)
Write-Host ("  geometry        : " + $r.authored.geometryResFilePath)
Write-Host ("  boosters        : " + $r.boosterItems)
Write-Host ("  turret locators : " + $r.turretLocators)
Write-Host ("  textures moved  : " + $r.textureChanges.Count)
Write-Host ("  aggregate hulls : " + $r.aggregate.beforeHullCount + " -> " + $r.aggregate.afterHullCount)
Write-Host ("  new hull present: " + $r.aggregate.newHullPresent)
