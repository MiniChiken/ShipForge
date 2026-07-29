@echo off
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat
if not exist "%VCVARS%" (
  echo vcvars64.bat not found at "%VCVARS%"
  exit /b 1
)
call "%VCVARS%" >nul
cd /d "%~dp0"
cl /nologo /std:c++17 /O2 /EHsc /I ref\include oodle1_cli.cpp ref\src\Oodle1.cpp /Fe:oodle1_cli.exe
exit /b %ERRORLEVEL%
