# 采集与构建流水线

本目录负责"从公开数据源采集 → 结构化 → AI 解读 → 生成看板与归档"的离线构建。

## 运行

```bash
# 完整构建（采集 + AI 解读 + 归档）
python3 news/build_dashboard.py --days 7 --synth

# 仅重建视图，不联网（调试模板时很快）
python3 news/build_dashboard.py --days 7 --no-news --no-lit --no-targets
```

常用参数：`--days`（新闻回溯天数）、`--jobs`（并发主题数）、`--synth`（生成 AI 解读，缺省即跳过）、`--no-news` / `--no-lit` / `--no-targets` / `--no-trials`（跳过对应采集，便于离线调试）。

产物：

```
output/dashboards/<YYYYMMDD>/index.html   静态看板（可归档、可直接分发）
output/dashboards/<YYYYMMDD>/data.json    结构化数据（webapp 读取）
output/dashboards/latest/                 最新一份的副本
output/cron.log                           定时任务日志
```

## 配置

所有主题与会议都在 `news/config.py`：

- `TOPICS`：常设疾病主题（采集条件、检索式、新闻查询）
- `CONFERENCES`：年度会议库（`anchor_ym` 会议归属年月、`refresh_after_days` 保鲜期）
- `DASHBOARD`：标题、品牌、图表口径等展示项

新增主题或会议**只需改配置**，构建与前端会自动适配。

## 数据分层与引用规范

| 层 | 数据源 | 来源索引形态 |
|---|---|---|
| 主证据 | PubTator 3（经 MedEvidence `tools/pubtator`） | `PMID` → PubMed |
| 主证据 | ClinicalTrials.gov API v2 | `NCT` → CT.gov |
| 主证据 | Open Targets（经 MedEvidence `tools/opentargets`） | Ensembl → OT |
| 补充 | Tavily | 原文 URL（明确标注"补充/非证据源"） |

构建过程用 `SourceBook` 统一登记来源并分配编号，AI 输出强制内联 `[n]`，随后由 `validate_citations()`
校验并重排编号。**不要绕过这一步直接拼接 AI 文本**，否则看板会出现"引用不存在"的编号。

## 依赖与外部服务

- Python 依赖见仓库根 `requirements.txt`
- `.env` 需 `TAVILY_API_KEY`、`DEEPSEEK_*`（任何 OpenAI 兼容端点）
- 可选：`MEDEX_PATH` 指向 MedEvidence 工具层（PubTator 3 / Open Targets 采集）。
  未配置时文献与靶点层为空，其余功能正常。

## 定时任务

`news/run_daily.sh` 可被 cron 或 launchd 调用，自带超时看门狗、失败重试与归档轮转；
环境变量 `PYTHON` / `BUILD_ARGS` / `KEEP_DAYS` / `BUILD_TIMEOUT` 可覆盖默认行为。

设计细节与已知陷阱见 [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)。