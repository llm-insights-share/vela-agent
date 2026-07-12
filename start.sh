#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

export SCREENPILOT_ENABLED=true

echo "=== 启动所有服务 ==="

# Start backend
echo "启动后端服务 (端口 8000)..."
cd "$BACKEND_DIR"
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload > "$PROJECT_DIR/backend.log" 2>&1 &
echo "后端服务已启动 (PID: $!), 日志: $PROJECT_DIR/backend.log"

# Start frontend
echo "启动前端服务 (端口 5173)..."
cd "$FRONTEND_DIR"
nohup npx vite --host 0.0.0.0 --port 5173 > "$PROJECT_DIR/frontend.log" 2>&1 &
echo "前端服务已启动 (PID: $!), 日志: $PROJECT_DIR/frontend.log"

echo "=== 所有服务已启动 ==="
echo "后端 API: http://localhost:8000/docs"
echo "前端页面: http://localhost:5173"

if [ "${SCREENPILOT_ENABLED}" = "true" ]; then
  echo "安装 ScreenPilot Playwright Chromium..."
  cd "$BACKEND_DIR"
  python -m playwright install chromium 2>/dev/null || true
fi