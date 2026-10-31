# 部署指南 · Deployment Guide

本项目是**纯本地运行**的 Python 应用（标准库 HTTP 服务 + 定时构建脚本），没有数据库、没有 Node 构建步骤、不依赖任何 SaaS。
部署只有四步：**装依赖 → 配 `.env` → 构建一次数据 → 起服务**。

> **最快的路径**：把下面那段提示词整段复制，粘贴到你的 AI agent 平台（DSH / Claude Code / Cursor / Codex / 通义灵码 / Coze 等可执行命令的 agent），让它自己完成部署。

---

## 路径 A（推荐）：复制提示词到 agent 平台，由 agent 部署

把**下面整段**复制粘贴给你的 agent。它会自己克隆仓库、装依赖、向你要密钥、构建数据、起服务并验证。

```text
请把 GitHub 仓库 https://github.com/ChrisLou-bioinfo/AImednews 部署到当前机器并启动看板。

【步骤】
1. 克隆仓库到当前目录下的 ./AImednews（已存在则 git pull）；进入该目录。
2. 检查 Python 版本（需 ≥ 3.10）。创建虚拟环境 .venv 并安装 requirements.txt 里的依赖。
3. 配置文件：若没有 .env，则复制 .env.example 为 .env。
   然后向我索取以下配置并写入 .env：
     - TAVILY_API_KEY（新闻/会议补充层，https://tavily.com 免费额度即可）
     - DEEPSEEK_BASE_URL / DEEPSEEK_MODEL / DEEPSEEK_API_KEY（任何 OpenAI 兼容端点都行；
       用本地 Ollama / vLLM 也可以，例如 http://127.0.0.1:11434/v1）
   如果我暂时没有密钥：不要卡住，直接用冒烟参数先跑起来（见步骤 4 的 B 方案），并告诉我补好密钥后怎么重跑。
4. 构建数据（二选一）：
   A. 已有密钥：   python news/build_dashboard.py --days 7 --synth
   B. 无密钥冒烟： python news/build_dashboard.py --days 7 --no-news --no-lit --no-targets
5. 后台启动服务： python webapp/server.py --port 8899
   然后验证 GET http://127.0.0.1:8899/api/health 返回 {"ok":true}，
   并确认 GET /api/data 能返回 JSON、首页 / 能正常打开。
6. 若本机有 systemd / cron / launchd，帮我配置每日 08:00 自动重建（调用 news/run_daily.sh），
   并把访问地址告诉我。
7. 最后汇报：访问 URL、数据构建产物路径（output/dashboards/...）、日志路径、仍缺失的配置项，
   以及停服/重启的命令。

【约束】
- 不要修改仓库里的业务代码；只通过 .env 与命令行参数配置。
- 不要使用 Docker，用本机 Python 虚拟环境部署即可。
- 遇到报错先查 docs/DEPLOY.md 末尾「常见问题」，不要把依赖反复重装。
- 端口 8899 被占用时改用 8900 并说明。
```

**agent 完成后你会拿到**：可访问的本地 URL、`output/dashboards/<日期>/` 数据产物、每日自动更新的定时任务。

> 为什么可以"复制即部署"：仓库里所有可变项都在 `.env` 与 `news/config.py`，没有写死的本机路径；
> 服务端除 `python-pptx` 外只用 Python 标准库；没有密钥时会自动降级为「仅本地渲染」而不是报错。

---

## 路径 B：本地手动安装

### 1. 环境要求

| 项 | 要求 |
|---|---|
| Python | ≥ 3.10（3.12 已验证） |
| 系统 | macOS / Linux（Windows 建议 WSL2） |
| 磁盘 | ≥ 300 MB（依赖 + 归档） |
| 网络 | 能访问 ClinicalTrials.gov / PubMed / Tavily / 你的 LLM 端点 |

### 2. 安装

```bash
git clone https://github.com/ChrisLou-bioinfo/AImednews.git
cd AImednews
bash scripts/setup.sh          # 建 venv、装依赖、生成 .env 模板、做一次构建
```

脚本是幂等的，可重复执行。没有 API Key 时它会自动做「冒烟构建」（不联网抓新闻/文献，先把界面跑起来）。

可选参数：

```bash
SKIP_BUILD=1 bash scripts/setup.sh                # 只装依赖，不构建
PYTHON=/usr/bin/python3.12 bash scripts/setup.sh  # 指定解释器
```

### 3. 配置密钥

```bash
cp .env.example .env      # 若 setup.sh 已生成则跳过
```

编辑 `.env`：

```ini
TAVILY_API_KEY=tvly-...                                   # 会议/新闻补充层

DEEPSEEK_BASE_URL=https://api.deepseek.com/v1             # 或任意 OpenAI 兼容端点
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...

# 可选：本地模型（无需联网、无需付费）
# DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1
# DEEPSEEK_MODEL=qwen2.5:32b
# DEEPSEEK_API_KEY=ollama

# 可选：MedEvidence 工具层（启用文献/靶点采集）
# MEDEX_PATH=/path/to/medevidence/medevidence_deploy/project
```

> **没有密钥也能部署**：Tavily 缺失 → 新闻/会议层为空；不传 `--synth` → 跳过 AI 解读；
> 试验数据（ClinicalTrials.gov 公共数据）与看板渲染完全不需要密钥。

### 4. 构建数据

```bash
. .venv/bin/activate

# 完整构建（需要密钥，首次约 5–20 分钟）
python news/build_dashboard.py --days 7 --synth

# 冒烟构建（不需要密钥，只拉试验 + 渲染本地页面）
python news/build_dashboard.py --days 7 --no-news --no-lit --no-targets
```

产物：`output/dashboards/<YYYYMMDD>/index.html`（可直接分发/归档的静态看板）与 `data.json`（服务端读取）。

### 5. 启动

```bash
python webapp/server.py --port 8899
# 打开 http://localhost:8899
```

验证：

```bash
curl -s http://127.0.0.1:8899/api/health          # 期望 {"ok":true}
curl -s http://127.0.0.1:8899/api/data | head -c 200
```

---

## 路径 C：常驻服务与每日自动更新

### Linux（systemd）

```bash
sudo cp deploy/aimednews.service deploy/aimednews-build.service deploy/aimednews-build.timer /etc/systemd/system/
sudo sed -i "s#__ROOT__#$(pwd)#g" /etc/systemd/system/aimednews*.{service,timer}
sudo systemctl daemon-reload
sudo systemctl enable --now aimednews                 # 看板常驻
sudo systemctl enable --now aimednews-build.timer     # 每日 08:00 重建
```

### macOS（launchd）

```bash
sed "s#__ROOT__#$(pwd)#g" deploy/com.aimednews.dashboard.plist.example \
  > ~/Library/LaunchAgents/com.aimednews.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.aimednews.dashboard.plist
```

### cron（通用）

```cron
0 8 * * * /path/to/AImednews/news/run_daily.sh
```

`news/run_daily.sh` 已内置超时看门狗、失败重试与 30 天归档轮转，可用
`PYTHON` / `BUILD_ARGS` / `KEEP_DAYS` / `BUILD_TIMEOUT` 覆盖默认行为。

### 对外访问（可选）

服务端本身**不内置鉴权**。多人访问时建议前置一层反向代理（Nginx / Caddy）并启用 HTTPS + Basic Auth；
或只在内网/本机使用。

---

## 部署后自检清单

- [ ] `GET /api/health` → `{"ok":true}`
- [ ] 首页可打开，左侧筛选与图表可用
- [ ] `output/dashboards/<日期>/data.json` 存在且 topics 非空
- [ ] 「导出 PPTX」能下载到可被 PowerPoint/WPS 打开的 `.pptx`
- [ ] 日志位置已确认：`output/cron.log`、`output/webapp.log`
- [ ] 停服命令已记录（`systemctl stop aimednews` / `pkill -f webapp/server.py`）

---

## 常见问题

**Q：启动报 `ModuleNotFoundError: No module named 'tavily'` / `dotenv` / `pptx`**
没有激活虚拟环境或依赖未安装。执行 `bash scripts/setup.sh`，或 `. .venv/bin/activate && pip install -r requirements.txt`。

**Q：构建时报 Tavily 401/429 或超时**
Key 错误或额度用尽（advanced 检索约 2 credits/次）。可先用冒烟参数构建；也可把
`news/config.py` 的 `search_depth` 改为 `basic` 降低消耗。

**Q：LLM 报 4xx/5xx 或超时**
确认 `DEEPSEEK_BASE_URL` 是**以 `/v1` 结尾的 OpenAI 兼容地址**、模型名正确、Key 有效。
也可换本地 Ollama（`http://127.0.0.1:11434/v1`，Key 可随便填）。

**Q：页面能开但所有主题都是空的**
说明只做了冒烟构建（未联网抓新闻/文献）。补好 `.env` 后重跑 `python news/build_dashboard.py --days 7 --synth`。

**Q：端口 8899 被占用**
`python webapp/server.py --port 8900`；或 `lsof -i:8899` 找到占用进程。

**Q：macOS launchd 定时任务不跑，日志里 "Operation not permitted"**
macOS 的 TCC 会拦截 launchd 访问 `~/Desktop`、`~/Documents` 等受保护目录。把项目移到不受保护的路径
（如 `~/code`），或给 `/bin/bash` 授予「完全磁盘访问权限」。另外 launchd 下不要用
`venv + PYTHONPATH` 的组合（易卡住），用系统 python + 全局依赖更稳。

**Q：Windows**
建议 WSL2（Ubuntu）按路径 B 执行；原生 Windows 未测试。

**Q：如何更新**
```bash
git pull
bash scripts/setup.sh                                  # 依赖有变更时会补齐
systemctl restart aimednews    # 或 pkill -f webapp/server.py 后重新启动
```

**Q：如何卸载**
停止服务后直接删除项目目录即可——没有系统级依赖、没有后台数据库。
若配置过 systemd/cron/launchd，记得一并移除对应单元或条目。

---

## 目录与权限

```
output/          构建产物与日志（建议定期备份，未纳入版本库）
.env             密钥文件（未纳入版本库，建议 chmod 600）
.venv/           虚拟环境（未纳入版本库）
```

---

## 许可提醒

本项目采用 **CC BY-NC 4.0（非商业）**：部署、使用、二次开发无需申请，但**对外交付、讲课、论文引用时必须署名**，
并保留作者邮箱 `loujiacheng1986@foxmail.com`（详见 [NOTICE.md](../NOTICE.md)）。商业使用请另行联系作者授权。
