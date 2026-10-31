#!/bin/bash
# 每日构建：重建肺癌情报看板（可手动执行，也可由 cron / launchd 调度）。
#
# 环境变量（均可选）：
#   PYTHON      指定解释器（默认 python3；需已安装 requirements.txt 依赖）
#   BUILD_ARGS  覆盖构建参数（默认 "--days 7 --synth"）
#   KEEP_DAYS   归档保留天数（默认 30）
set -u

# 项目根目录：由脚本位置推导，不依赖调用者的当前目录
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
LOG="$ROOT/output/cron.log"
BUILD_ARGS="${BUILD_ARGS:---days 7 --synth}"
KEEP_DAYS="${KEEP_DAYS:-30}"
TIMEOUT="${BUILD_TIMEOUT:-2400}"

mkdir -p "$ROOT/output"
cd "$ROOT" || exit 1

# 部分依赖（tiktoken）首次使用会联网下载；固定缓存目录，避免后台环境卡住
export TIKTOKEN_CACHE_DIR="${TIKTOKEN_CACHE_DIR:-$HOME/.cache/tiktoken}"

build_once() {
  "$PY" "$ROOT/news/build_dashboard.py" $BUILD_ARGS &
  local PID=$!
  ( sleep "$TIMEOUT"; kill -9 "$PID" 2>/dev/null ) & local WD=$!
  wait "$PID"
  local rc=$?
  kill "$WD" 2>/dev/null
  return $rc
}

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') start ====="
  # 网络波动下偶发卡顿：带超时看门狗 + 失败重试一次
  build_once || { echo "[retry] 首轮异常/超时，重试一次…"; build_once; }
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') done ====="
} >> "$LOG" 2>&1

# 归档轮转：仅保留最近 KEEP_DAYS 个日期目录（跨平台写法，不含 GNU 专有参数）
cd "$ROOT/output/dashboards" 2>/dev/null || exit 0
ls -1dt 20* 2>/dev/null | tail -n +$((KEEP_DAYS + 1)) | while IFS= read -r d; do
  [ -n "$d" ] && rm -rf -- "$d"
done
