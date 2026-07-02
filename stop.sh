#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 停止所有服务 ==="

# Stop backend (port 8000)
BACKEND_PID=$(lsof -ti:8000 2>/dev/null || true)
if [ -n "$BACKEND_PID" ]; then
    echo "停止后端服务 (PID: $BACKEND_PID)..."
    kill $BACKEND_PID 2>/dev/null || true
    sleep 1
    kill -9 $BACKEND_PID 2>/dev/null || true
    echo "后端服务已停止"
else
    echo "后端服务未运行"
fi

# Stop frontend (port 5173)
FRONTEND_PID=$(lsof -ti:5173 2>/dev/null || true)
if [ -n "$FRONTEND_PID" ]; then
    echo "停止前端服务 (PID: $FRONTEND_PID)..."
    kill $FRONTEND_PID 2>/dev/null || true
    sleep 1
    kill -9 $FRONTEND_PID 2>/dev/null || true
    echo "前端服务已停止"
else
    echo "前端服务未运行"
fi

echo "=== 所有服务已停止 ==="