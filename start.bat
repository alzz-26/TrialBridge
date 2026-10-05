@echo off
REM TrialBridge: double-click to start. Opens http://localhost:8000 in your browser.
REM First run downloads the demo data (~15 MB) and Python packages (~1 GB). Later runs start in under a minute.
cd /d "%~dp0"

if not exist "data\trialbridge.db" (
  echo Downloading demo data bundle...
  curl -L -o trialbridge-demo-data.zip https://github.com/alzz-26/TrialBridge/releases/download/v0.1.0/trialbridge-demo-data.zip || goto :nodata
  tar -xf trialbridge-demo-data.zip || goto :nodata
  del trialbridge-demo-data.zip
)

where uv >nul 2>nul || (
  echo uv is not installed. Open PowerShell and run:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  echo then close and re-open this window.
  pause
  exit /b 1
)

cd backend
uv sync || (pause & exit /b 1)
start "" cmd /c "timeout /t 25 >nul & start http://localhost:8000"
uv run trialbridge serve
pause
exit /b 0

:nodata
echo Could not download the demo data. See "Get the demo data" in README.md.
pause
exit /b 1
