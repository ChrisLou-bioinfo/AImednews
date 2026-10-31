#!/usr/bin/env bash
# 一键安装/初始化脚本（macOS / Linux）
# 用法：
#   bash scripts/setup.sh              # 安装依赖 + 生成 .env 模板 + 冒烟构建
#   SKIP_BUILD=1 bash scripts/setup.sh # 只装依赖，不构建
#   PYTHON=/usr/bin/python3.12 bash scripts/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"

say() { printf "\n\033[1m▸ %s\033[0m\n" "$*"; }
warn() { printf "\033[33m  ! %s\033[0m\n" "$*"; }

command -v "$PY" >/dev/null 2>&1 || { echo "找不到 python（可用 PYTHON=/path/to/python3 指定）"; exit 1; }

say "检查 Python 版本"
"$PY" - <<'PYCHK'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"需要 Python ≥ 3.10，当前 {sys.version.split()[0]}")
print(f"  Python {sys.version.split()[0]} 可用")
PYCHK

say "创建虚拟环境 .venv"
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --quiet --upgrade pip

say "安装依赖（requirements.txt）"
python -m pip install --quiet -r requirements.txt
echo "  依赖安装完成"

say "准备配置文件"
if [ -f .env ]; then
  echo "  .env 已存在，跳过"
else
  cp .env.example .env
  warn "已生成 .env：请填入 TAVILY_API_KEY 与 DEEPSEEK_* 后重新运行本脚本（或先跑冒烟模式）"
fi

# 是否具备联网采集所需配置
has_keys=0
if [ -f .env ]; then
  grep -qE '^TAVILY_API_KEY=.+' .env 2>/dev/null && has_keys=1
fi

if [ "${SKIP_BUILD:-0}" = "1" ]; then
  say "跳过数据构建（SKIP_BUILD=1）"
else
  if [ "$has_keys" = "1" ]; then
    say "构建数据（完整采集 + AI 解读，首次约 5–20 分钟）"
    python news/build_dashboard.py --days 7 --synth
  else
    say "未检测到 TAVILY_API_KEY → 执行冒烟构建（仅本地渲染，不联网）"
    python news/build_dashboard.py --days 7 --no-news --no-lit --no-targets
    warn "补好 .env 后请重新运行本脚本，或手动执行：python news/build_dashboard.py --days 7 --synth"
  fi
fi

cat <<DONE

$(printf '\033[1m▸ 安装完成\033[0m')

  启动看板：
      . .venv/bin/activate
      python webapp/server.py --port 8899
      # 浏览器打开 http://localhost:8899

  每日自动构建（可选）：
      Linux:   0 8 * * * $ROOT/news/run_daily.sh
      macOS:   sed "s#__ROOT__#$ROOT#g" deploy/com.aimednews.dashboard.plist.example \\
                 > ~/Library/LaunchAgents/com.aimednews.dashboard.plist
      systemd: sudo cp deploy/aimednews.service /etc/systemd/system/ \\
               && sudo systemctl enable --now aimednews

  文档：docs/DEPLOY.md
DONE
