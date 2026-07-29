@echo off
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat
call "%VCVARS%" >nul
cd /d "%~dp0"
cl /nologo /std:c++17 /O2 /EHsc py27c.cpp /Fe:py27c.exe
exit /b %ERRORLEVEL%
