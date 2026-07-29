@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /nologo /std:c++17 /O2 /EHsc py27shim.cpp /Fe:py27shim.exe
exit /b %ERRORLEVEL%
