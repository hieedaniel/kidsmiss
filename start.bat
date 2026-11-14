@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "web\dist\index.html" (
  echo [1/2] Building frontend for the first time...
  pushd web
  call npm install --no-audit --no-fund
  call npm run build
  popd
)

echo [2/2] Starting server on http://127.0.0.1:8770
start "" http://127.0.0.1:8770
python server\main.py --port 8770
pause
