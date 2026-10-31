# 架构与设计说明

本文档面向想二次开发或自部署的人，说明数据流、关键约束和已知陷阱。

## 1. 总体数据流

```
                 ┌──────────────────────────── 采集（news/build_dashboard.py）────────────────────────────┐
ClinicalTrials.gov ─┐                                                                                       
PubTator 3 / PubMed ─┼─► collect_*()  ─► SourceBook（统一证据登记：kind/label/url → 递增编号 n）            
Open Targets ────────┤                         │                                                             
Tavily（补充层）─────┘                         ▼                                                             
                                    AI 解读（强制内联 [n] 引用）                                             
                                              │                                                              
                                    validate_citations()（越界编号剔除 + 编号重排）                           
                                              │                                                              
                     ┌────────────────────────┴────────────────────────┐                                    
                     ▼                                                 ▼                                    
      output/dashboards/<日期>/index.html                output/dashboards/<日期>/data.json              
      （静态只读看板，可归档/分发）                        （机器可读，供 webapp 使用）                    
                                                                        │                                    
                                                                        ▼                                    
                                              webapp/server.py（合并归档 + 实时试验层 + 导出）              
                                                     │                    │                                
                                                     ▼                    ▼                                
                                            交互看板 index.html      /api/pptx → ppt_deck.py（可编辑 PPTX）
```

## 2. 证据与引用机制（核心约束）

- `SourceBook` 是唯一的证据登记处：任何进入 AI 上下文的材料都必须先登记，得到全局递增编号。
- AI 输出被要求对每个事实性陈述标注 `[n]`。
- `validate_citations()` 做三件事：剔除不存在的编号、剔除未使用的来源（避免索引虚胖）、按保留项重排编号。
- 静态看板与 webapp 都以该编号体系渲染"来源索引"，点击可跳原始链接。

**为什么强制**：LLM 在长上下文里容易"自信地编引文"。把引文变成可机械校验的编号，是让"可溯源"从口号变成约束的最低成本做法。

## 3. 采集层要点

| 模块 | 接口 | 备注 |
|---|---|---|
| 试验 | ClinicalTrials.gov API v2 `query.cond` + `query.term` | 用 cond 限定瘤种；早期用 term 直接塞 "MET lung cancer" 会误匹配 mother-to-child transmission |
| 文献 | PubTator 3 `search_text` + `export_pmids`；PubMed E-utilities 补 pubdate | 需要 `MEDEX_PATH` 指向 MedEvidence；未安装时该层为空，其余功能不受影响 |
| 靶点 | Open Targets GraphQL `drug.maximumClinicalStage` | 字段名随版本变化，出错时优先核对 schema |
| 新闻/会议 | Tavily（需 Key） | 仅作背景层；会议卡另做"报道正文 → 结构化结果表"抽取 |

会议卡额外机制：

- `anchor_ym`：会议归属年月，用于时间筛选的整卡纳入/排除（会议报道常无可靠发布日期）。
- `refresh_after_days`：超过阈值直接复用最近归档，避免每日重复消耗检索额度。
- `expected_trials`（可选）：给出该会议的关键试验清单，构建时检测缺口并定向补搜（成本较高，建议只给当期会议）。

## 4. webapp（交互看板）

- 纯 Python 标准库 HTTP 服务（`http.server`）+ 单文件前端，无构建步骤、无 Node 依赖。
- `GET /api/data`：合并 `output/dashboards/*` 归档（去重、按最新结构）+ 实时试验层，带 TTL 缓存。
- `POST /api/ask`：情报问答，生成带引用的专题卡。
- `POST /api/report`：当前筛选范围的总结报告。
- `GET|POST /api/pptx`：导出 PPTX。

### 筛选语义（重要）

导出遵循"所见即所得"：前端用与界面完全相同的筛选函数算出命中集合（试验 NCT / 文献 PMID / 新闻 URL），
以 `sel` 结构提交，服务端**只按这些 key 精确裁剪**，不在服务端重复实现筛选规则（避免两套逻辑漂移）。

时间筛选对会议卡的处理：

1. 会议卡按 `anchor_ym` 判定；不匹配则整卡排除（含无日期的关键试验表）。
2. 非会议主题若无任何时间命中项，其无日期内容（靶点、会议表）一并剔除，避免"空壳主题"占页。
3. 剔除会议后若结果为空（例如只筛了某次会议月），自动回退保留会议，避免导出空 PPT。

## 5. PPTX 生成（ppt_deck.py）

- 使用 `python-pptx` 生成 16:9 原生图表与表格（可在 PowerPoint 中编辑，非图片）。
- 版式统一由常量控制（配色、字体、页边距），每页带页眉页脚与来源标注。
- 页面：封面 → 数据总览 → 情报体系 → 结构图表 → 各主题（AI 解读 + 主题机制图 + 在研试验 + 关键文献）→（可选）会议关键试验表 → 来源索引 → 小结。

**中文字体约束**：`Arial Unicode MS` 是实测在 LibreOffice/PowerPoint 下中英混排不丢字的稳妥选择；
`a:ea`（东亚字体）元素必须紧跟 `a:latin`，否则字形会错乱（`python-pptx` 没有 `ea` API，需手工插入并保证顺序）。

## 6. 定时与运维

`news/run_daily.sh`：带超时看门狗 + 失败重试一次 + 归档轮转（默认保留 30 天）。

macOS 上踩过的坑（Linux 不涉及）：

- launchd 下 `cwd=/` 曾导致 Python 初始化阶段 `open()` 卡死 —— 脚本必须 `cd` 到项目根目录。
- launchd/cron 读取 `~/Desktop` 会被 TCC 拦截（Operation not permitted）—— 项目放在受保护目录时需给 `/bin/bash`、`cron` 或解释器授权，或把项目移出 Desktop。
- launchd 下 `venv` / `PYTHONPATH` 组合易卡（原因未明），实测"系统/Homebrew 基础解释器 + 全局安装依赖"最稳。

## 7. 扩展点

| 想做的事 | 改哪里 |
|---|---|
| 新增疾病主题 | `news/config.py` 的 `TOPICS` |
| 新增会议 | `news/config.py` 的 `CONFERENCES`（纯配置，无需改代码） |
| 换 AI 端点 | `.env` 的 `DEEPSEEK_*`（任何 OpenAI 兼容接口） |
| 改 PPT 版式 | `webapp/ppt_deck.py` 中的版式常量与各 `_slide_*` 函数 |
| 加新数据源 | `news/build_dashboard.py` 新增 `collect_*`，并登记进 `SourceBook` |