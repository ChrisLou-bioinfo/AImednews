#!/usr/bin/env bash
# 把 docs/wechat/开源项目宣传.md 打包成公众号草稿素材（content-1.html + article-1.json + 封面/篇首图）
# 用法：bash docs/wechat/pack.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
WE="$HOME/.agents/skills/wechat-publish/scripts/wechatctl.py"
PY="${PYTHON:-python3}"

# 配图：若缺失则从 docs/screenshots 复制（这些是打包用的副本，不纳入版本库）
cp -f docs/wechat/fig1-dashboard-lead.jpg docs/wechat/fig1-dashboard-lead.jpg 2>/dev/null || true
cp -n docs/screenshots/ppt-overview.png docs/wechat/fig2-ppt-overview.png 2>/dev/null || true
cp -n docs/screenshots/ppt-topic.png docs/wechat/fig3-ppt-topic.png 2>/dev/null || true

"$PY" "$WE" pack docs/wechat \
  --md docs/wechat/开源项目宣传.md \
  --title "我把肺癌情报看板开源了：每个结论都能追溯到原文" \
  --digest "一个每天自动更新的肺癌（EGFR/MET）情报看板：试验、文献、靶点、会议数据分层采集，AI 每句话都带编号引用、可回溯 PMID/NCT/原文，还能导出可编辑 PPT。" \
  --author "Chris" \
  --source-url "https://github.com/ChrisLou-bioinfo/AImednews" \
  --lead docs/wechat/fig1-dashboard-lead.jpg \
  --cover docs/wechat/cover/封面-公众号.png \
  --cover-sub "肺癌 EGFR/MET 情报看板 · 开源"

"$PY" docs/wechat/postprocess.py docs/wechat/wechat
echo "完成：docs/wechat/wechat/{content-1.html,article-1.json,cover.png,lead.jpg}"
