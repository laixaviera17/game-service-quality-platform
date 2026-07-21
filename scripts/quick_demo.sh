#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 启动 Docker 栈（MySQL / Redis / API / Celery Worker）"
docker compose up --build -d

echo "==> 等待 /health 就绪"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:8000/health | python3 -m json.tool

echo
echo "==> 30 秒体验路径"
echo "1) 浏览器打开: http://127.0.0.1:8000/dashboard"
echo "2) 先运行「账本守卫失效对照」，期望状态: detected（琥珀色「已检出」）"
echo "3) 再运行「并行消费尝试」，在时间线查看两个 Outbox 轮询 task_id"
echo
echo "可选 API 快速验证:"
echo "  curl -X POST http://127.0.0.1:8000/reliability/runs -H 'Content-Type: application/json' -d '{\"scenario\":\"guard_disabled_control\"}'"
