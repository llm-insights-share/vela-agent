#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
LETTA_DIR="$BACKEND_DIR/letta"
LETTA_PORT="${LETTA_PORT:-8283}"

export SCREENPILOT_ENABLED=true
export SCREENPILOT_HEADLESS=true   # 无头

echo "=== 启动所有服务 ==="

# Start backend first (Letta LLM/embedding gateway depends on :8000)
echo "启动后端服务 (端口 8000)..."
cd "$BACKEND_DIR"
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload > "$PROJECT_DIR/backend.log" 2>&1 &
echo "后端服务已启动 (PID: $!), 日志: $PROJECT_DIR/backend.log"

# Wait briefly for backend so Letta can reach /llm-gateway
echo "等待后端就绪..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf "http://127.0.0.1:8000/api/v1/health" >/dev/null 2>&1 \
     || curl -sf "http://127.0.0.1:8000/docs" >/dev/null 2>&1; then
    echo "后端已就绪"
    break
  fi
  sleep 1
done

# Start Letta memory server (port 8283)
if [ "${SKIP_LETTA:-}" = "1" ]; then
  echo "跳过 Letta (SKIP_LETTA=1)"
else
  echo "启动 Letta 记忆服务 (端口 ${LETTA_PORT})..."
  if [ -x "$LETTA_DIR/start_letta.sh" ]; then
    # Ensure nothing stale is bound to the port
    OLD_LETTA=$(lsof -ti:"$LETTA_PORT" 2>/dev/null || true)
    if [ -n "$OLD_LETTA" ]; then
      echo "端口 ${LETTA_PORT} 已被占用 (PID: $OLD_LETTA)，先停止..."
      kill $OLD_LETTA 2>/dev/null || true
      sleep 1
      kill -9 $OLD_LETTA 2>/dev/null || true
    fi
    cd "$LETTA_DIR"
    nohup bash ./start_letta.sh > "$PROJECT_DIR/letta.log" 2>&1 &
    echo "Letta 已启动 (PID: $!), 日志: $PROJECT_DIR/letta.log"
  else
    echo "未找到 $LETTA_DIR/start_letta.sh，跳过 Letta"
  fi
fi

# Start frontend
echo "启动前端服务 (端口 5173)..."
cd "$FRONTEND_DIR"
nohup npx vite --host 0.0.0.0 --port 5173 > "$PROJECT_DIR/frontend.log" 2>&1 &
echo "前端服务已启动 (PID: $!), 日志: $PROJECT_DIR/frontend.log"

echo "=== 所有服务已启动 ==="
echo "后端 API: http://localhost:8000/docs"
echo "Letta 记忆: http://localhost:${LETTA_PORT}"
echo "前端页面: http://localhost:5173"

if [ "${SCREENPILOT_ENABLED}" = "true" ]; then
  echo "安装 ScreenPilot Playwright Chromium..."
  cd "$BACKEND_DIR"
  python -m playwright install chromium 2>/dev/null || true
fi
