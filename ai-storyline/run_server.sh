#!/bin/sh
# 启动「歧路」Web服务
# 配置优先读 .env（含 LLM_API_KEY / STORY_MODE），也可用环境变量覆盖：
#   ./run_server.sh                          （读取 .env）
#   STORY_MODE=mock ./run_server.sh          （强制Mock模式）
cd "$(dirname "$0")"
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
exec .venv/bin/uvicorn server.app:app --host 127.0.0.1 --port 8000 "$@"
