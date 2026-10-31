# -*- coding: utf-8 -*-
"""
肺癌 EGFR/MET NSCLC 情报看板 v2 —— 主题配置。

数据源分层（v2）：
  主证据（MedEvidence 体系，全部带编号来源索引）：
    - PubTator 3      文献（PMID + 实体标注）      → pt_query
    - ClinicalTrials  临床试验（NCT）              → ct_cond + ct_term（cond 锚定病种，防跑偏）
    - OpenTargets     靶点-疾病-药物（含临床阶段）  → genes
  补充：
    - Tavily          新闻情报（仅作补充，明确标注）→ news_queries

每个主题的 AI 结论强制引用上述来源编号，构建时做引用校验（防幻觉编号）。
"""

TOPICS = [
    {
        "id": "egfr_l1_later",
        "title": "EGFR 突变晚期 NSCLC 一线及后线治疗新进展",
        "subtitle": "First-line & later-line treatment advances in EGFR-mutant NSCLC",
        "genes": ["EGFR"],
        "pt_query": "EGFR mutant non-small cell lung cancer first-line osimertinib",
        "news_queries": [
            "EGFR 突变 晚期 非小细胞肺癌 一线治疗 新进展",
            "EGFR mutant NSCLC first-line treatment 2026",
            "EGFR mutated lung cancer latest clinical trial results",
        ],
        "ct_cond": "Non-Small Cell Lung Cancer",
        "ct_term": "EGFR first-line OR EGFR TKI",
    },
    {
        "id": "egfr_tp53",
        "title": "EGFR 合并 TP53 晚期 NSCLC 一线治疗进展",
        "subtitle": "First-line therapy for EGFR plus TP53 co-mutated NSCLC",
        "genes": ["EGFR", "TP53"],
        "pt_query": "EGFR TP53 co-mutation non-small cell lung cancer",
        "news_queries": [
            "EGFR TP53 共突变 非小细胞肺癌 一线治疗",
            "EGFR TP53 co-mutation NSCLC first-line",
            "TP53 comutation EGFR lung cancer prognosis treatment",
        ],
        "ct_cond": "Non-Small Cell Lung Cancer",
        "ct_term": "EGFR TP53",
    },
    {
        "id": "egfr_resistance",
        "title": "EGFR 突变 NSCLC 耐药后治疗策略",
        "subtitle": "Treatment strategies after acquired resistance to EGFR TKIs",
        "genes": ["EGFR"],
        "pt_query": "EGFR TKI acquired resistance non-small cell lung cancer osimertinib",
        "news_queries": [
            "EGFR 突变 非小细胞肺癌 耐药 治疗策略 后线",
            "EGFR TKI acquired resistance treatment strategy NSCLC",
            "osimertinib resistance mechanisms treatment 2026",
        ],
        "ct_cond": "Non-Small Cell Lung Cancer",
        "ct_term": "EGFR resistance OR osimertinib resistance",
    },
    {
        "id": "met_primary",
        "title": "原发 MET 异常肺癌靶向治疗进展解读",
        "subtitle": "Targeted therapy for primary MET-altered lung cancer",
        "genes": ["MET"],
        "pt_query": "MET exon 14 skipping NSCLC MET amplification targeted therapy",
        "news_queries": [
            "原发 MET 异常 肺癌 靶向治疗 进展",
            "MET exon 14 skipping lung cancer targeted therapy 2026",
            "MET amplification lung cancer crizotinib capmatinib latest",
        ],
        "ct_cond": "Non-Small Cell Lung Cancer",
        "ct_term": "MET exon 14 OR MET amplification",
    },
]

# ═══════════════════════ 年度学术会议库（新药疗效临床试验报道汇总） ═══════════════════════
# 设计说明：
#   - 每年每个大会一条；build 时自动生成"会议速递"主题卡（关键试验结果表 + 会议报道汇总）。
#   - anchor_ym 是会议内容所属年月：时间筛选按它整卡纳入/排除，避免 9 月筛选带出 10 月会议内容。
#   - 历史会议（距今超过 refresh_after_days）会直接复用最近归档里的结果，不再重复抓取，节省额度。
#   - 新增会议只需照格式追加一条；expected_trials 可选（用于缺口补搜，成本较高，建议只给当期大会）。
CONFERENCES = [
{
        # 会议速递：ESMO 内容以 PubMed(ESMO/ESMO Open 期刊) + 长窗口新闻为主，
        # 不重复抓试验（试验已在上面四个主题覆盖）。
        "id": "esmo_congress",
        "title": "ESMO 2026 会议速递（EGFR/MET NSCLC）",
        "subtitle": "Latest ESMO congress evidence in EGFR/MET-altered NSCLC",
        "genes": ["EGFR", "MET"],
        "paper_source": "pubmed",
        "pubmed_query": ('(ESMO[Title] OR "ESMO Open"[Journal]) AND '
                         '(NSCLC[Title/Abstract] OR '
                         '"non-small cell lung"[Title/Abstract])'),
        "skip_trials": True,
        "news_days": 120,
        # 日期锚点：ESMO 2026 年会内容整体属于 2026 年 10 月。
        # 时间筛选（年/月）不匹配时，整张会议卡（含无日期的关键试验表）应被排除。
        "anchor_ym": "2026-10",
        "news_cap": 14,
        "papers_display": 12,
        "papers_search": 24,
        "extract_key_trials": True,
        # ESMO 2026 关键注册试验清单：用于检测抽取缺口并定向补齐
        "expected_trials": [
            "RASolute 302", "DeLLphi-305", "CLARITY-Gastric 01", "KEYNOTE-905",
            "ARTEMIS-011", "KRAScendo 1", "G-HOPE-001", "VOLGA", "SAFFRON",
            "TroFuse-005", "OptiTROP-Lung04", "HARMONi-GI1", "KEYNOTE-C93",
            "ASTRIDE", "ENERGIZE", "KEYNOTE-866", "SANOVO", "INTerpath-001",
            "lidERA", "DOVACC", "DASL-HiCaP", "OptiTROP-Lung06",
        ],
        "news_queries": [
            "ESMO 2026 关键试验 结果 汇总 阳性",
            "ESMO 2026 presidential symposium results",
            "ESMO 2026 late-breaking abstracts results",
            "ESMO 2026 NSCLC EGFR 最新结果 公布",
            "ESMO 2026 MET exon 14 lung cancer results",
            "ESMO congress 2026 non-small cell lung cancer highlights",
            "ESMO 2026 全部 研究 数据 一览",
            "ESMO 2026 ADCs new combinations lung cancer",
            "ESMO 2026 practice-changing trials summary hazard ratio",
            "ESMO 2026 late-breaking phase 3 results table all tumour types",
            "ESMO 2026 congress highlights all tumour types",
        ],
    },
    {
        "id": "conf_wclc_2026",
        "title": "WCLC 2026 会议速递（世界肺癌大会）",
        "subtitle": "WCLC 2026 new drug efficacy trial reports",
        "anchor_ym": "2026-09",
        "news_queries": [
            "WCLC 2026 关键试验 结果 公布",
            "WCLC 2026 lung cancer trial results",
            "WCLC 2026 late-breaking abstracts efficacy",
            "WCLC 2026 新药 疗效 数据",
        ],
        "news_cap": 12,
        "news_days": 150,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": True,
        "refresh_after_days": 200,
    },
    {
        "id": "conf_asco_2026",
        "title": "ASCO 2026 会议速递（美国临床肿瘤学会）",
        "subtitle": "ASCO 2026 new drug efficacy trial reports",
        "anchor_ym": "2026-06",
        "news_queries": [
            "ASCO 2026 关键试验 结果 汇总",
            "ASCO 2026 annual meeting practice-changing trials",
            "ASCO 2026 late-breaking abstract results",
            "ASCO 2026 新药 疗效 临床 数据",
        ],
        "news_cap": 12,
        "news_days": 210,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": True,
        "refresh_after_days": 200,
    },
    {
        "id": "conf_aacr_2026",
        "title": "AACR 2026 会议速递（美国癌症研究协会）",
        "subtitle": "AACR 2026 new drug efficacy trial reports",
        "anchor_ym": "2026-04",
        "news_queries": [
            "AACR 2026 关键试验 结果",
            "AACR 2026 annual meeting clinical trial results",
            "AACR 2026 new drug efficacy data",
            "AACR 2026 新药 临床 数据 公布",
        ],
        "news_cap": 12,
        "news_days": 240,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": True,
        "refresh_after_days": 200,
    },
    {
        "id": "conf_esmo_asia_2026",
        "title": "ESMO Asia 2026 会议速递",
        "subtitle": "ESMO Asia 2026 new drug efficacy trial reports",
        "anchor_ym": "2026-12",
        "news_queries": [
            "ESMO Asia 2026 关键试验 结果",
            "ESMO Asia 2026 abstract results",
            "ESMO Asia 2026 new drug efficacy data",
        ],
        "news_cap": 10,
        "news_days": 120,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": True,
        "refresh_after_days": 200,
    },
]


DASHBOARD = {
    "title": "肺癌 EGFR/MET NSCLC 科研情报看板",
    "subtitle": "MedEvidence 证据体系为主 · 全文来源索引 · Tavily 新闻补充",
    "author": "AImednews",
    "default_days": 21,
    "search_depth": "advanced",   # Tavily: basic=1 credit/次, advanced=2 credits/次
    "top_news_per_topic": 5,      # Tavily 为补充源，数量受控
    "max_trials_per_topic": 8,
    "max_papers_display": 6,      # 展示篇数（检索更多后按年份取最新）
    "max_papers_search": 12,
}
