#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f web/dist/index.html ]; then
  echo "[1/2] 首次运行，构建前端…"
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

echo "[2/2] 启动服务 http://127.0.0.1:8770"
python server/main.py --port 8770
