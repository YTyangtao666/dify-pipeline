#!/bin/bash
# 每日定时触发 Dify 工作流跑全链路（launchd 调用）
set -u

DIFY_BASE="http://127.0.0.1/v1"
# API key 从 .env 读取（勿硬编码入库）
set -a; source "$(cd "$(dirname "$0")/.." && pwd)/.env"; set +a
PRODUCT_ID="${1:-P001}"

resp=$(curl -sS --max-time 7200 -X POST "$DIFY_BASE/workflows/run" -H "Authorization: Bearer $DIFY_API_KEY" -H "Content-Type: application/json" -d "{\"inputs\":{\"product_id\":\"$PRODUCT_ID\",\"gen_limit\":2},\"response_mode\":\"blocking\",\"user\":\"cron\"}")

echo "[$(date '+%F %T')] trigger $PRODUCT_ID"
echo "$resp" | tail -c 500
status=$(echo "$resp" | /usr/bin/python3 -c "import sys,json;print(json.load(sys.stdin).get('data',{}).get('status','?'))" 2>/dev/null || echo parse_err)
echo "status=$status"
[ "$status" = "succeeded" ] || exit 1
