@echo off
rem Start the live-captions server and say which page to open (Windows).
rem Usage: double-click run.bat, or run it from a terminal. Ctrl-C stops the server
rem (the current recording and transcript are saved on the way out).
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is not installed. In PowerShell run:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  echo then open a new terminal and run run.bat again.
  pause
  exit /b 1
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo Created .env from .env.example ^(stand-in engines, no cloud^). Add your API keys to .env for real captions.
)

set "PORT=8765"
set "HOST=127.0.0.1"
set "STT_ENGINE=stub"
set "TRANSLATE_ENGINE=stub"
rem Read settings from .env: NAME=value, with an optional " # comment" after the value.
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  set "name=%%A"
  set "value=%%B"
  if defined value (
    for /f "tokens=1 delims=#" %%C in ("!value!") do set "value=%%C"
    for /f "tokens=* delims= " %%D in ("!value!") do set "value=%%D"
    call :trim value
    if /i "!name!"=="PORT" if not "!value!"=="" set "PORT=!value!"
    if /i "!name!"=="HOST" if not "!value!"=="" set "HOST=!value!"
    if /i "!name!"=="STT_ENGINE" if not "!value!"=="" set "STT_ENGINE=!value!"
    if /i "!name!"=="TRANSLATE_ENGINE" if not "!value!"=="" set "TRANSLATE_ENGINE=!value!"
  )
)

netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo Port %PORT% is already in use: the server may already be running. Open http://localhost:%PORT%/
  pause
  exit /b 1
)

echo.
echo   live-captions - speech: %STT_ENGINE%, translation: %TRANSLATE_ENGINE%
echo.
echo   ^> Open the control page in Chrome on THIS computer:
echo       http://localhost:%PORT%/
echo     Pick the mixer input, press Start listening, paste the Zoom caption link if needed,
echo     then open the caption window from there.
if "%HOST%"=="0.0.0.0" echo     Other machines on the network can open the caption display; the control page shows the link.
set "STUB="
if /i "%STT_ENGINE%"=="stub" set "STUB=1"
if /i "%TRANSLATE_ENGINE%"=="stub" set "STUB=1"
if defined STUB (
  echo.
  echo   Note: stand-in engines are on ^(no real speech recognition or translation^).
  echo         Set STT_ENGINE / TRANSLATE_ENGINE and the API keys in .env for the real thing.
)
echo.
echo   Ctrl-C stops the server ^(the current recording and transcript are saved^).
echo.

uv run python -m app
echo.
echo Server stopped.
pause
exit /b 0

:trim
rem Remove trailing spaces from the variable named %1.
:trim_loop
if "!%1:~-1!"==" " (
  set "%1=!%1:~0,-1!"
  goto trim_loop
)
exit /b 0
