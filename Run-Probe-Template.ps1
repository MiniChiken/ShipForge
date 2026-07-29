$ErrorActionPreference="Stop"
$here=Split-Path -Parent $MyInvocation.MyCommand.Path
$kit=Join-Path $here "kit\EVE-New-Ship-Native-Authoring-Kit-build3396210"
$clientTq="C:\EVE-EVEJS\client\EVE\tq"
$env:PYTHONHOME=Join-Path $kit "runtime\python27"
$env:PYTHONPATH=Join-Path $kit "runtime\python27\Lib"
$env:ELYSIAN_SHIPKIT_RESFILES="C:\EVE-EVEJS\client\EVE\ResFiles"
$result=Join-Path $here "probe_template_result.json"
Remove-Item -LiteralPath $result -ErrorAction SilentlyContinue
Push-Location $clientTq
try { & (Join-Path $clientTq "bin64\exefile.exe") /py (Join-Path $here "probe_template.py") $result (Join-Path $here "probe_template_request.json") /inherit } finally { Pop-Location }
$d=(Get-Date).AddSeconds(600); while(-not (Test-Path $result)){ if((Get-Date) -ge $d){throw "timeout"}; Start-Sleep -Milliseconds 300 }
"probed"
