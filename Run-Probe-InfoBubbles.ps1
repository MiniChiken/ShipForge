# NO PYTHONHOME/PYTHONPATH override: the fsdlite package lives in code.ccp and
# needs the client's own import hook, which our kit-runtime environment shadows.
$ErrorActionPreference="Stop"
$here=Split-Path -Parent $MyInvocation.MyCommand.Path
$clientTq="C:\EVE-EVEJS\client\EVE\tq"
$env:ELYSIAN_SHIPKIT_RESFILES="C:\EVE-EVEJS\client\EVE\ResFiles"
$result=Join-Path $here "probe_infobubbles_result.json"
Remove-Item -LiteralPath $result -ErrorAction SilentlyContinue
Push-Location $clientTq
try { & (Join-Path $clientTq "bin64\exefile.exe") /py (Join-Path $here "probe_infobubbles.py") $result (Join-Path $here "probe_infobubbles_request.json") /inherit } finally { Pop-Location }
$d=(Get-Date).AddSeconds(900); while(-not (Test-Path $result)){ if((Get-Date) -ge $d){throw "timeout"}; Start-Sleep -Milliseconds 300 }
"probed"
