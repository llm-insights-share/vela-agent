#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 重启所有服务 ==="
bash "$PROJECT_DIR/stop.sh"
echo ""
bash "$PROJECT_DIR/start.sh"