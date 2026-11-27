# -*- coding: utf-8 -*-
"""
血液肿瘤（含儿童）情报看板 —— 主题配置。

用途：血液肿瘤论坛讲课（重点：儿童血液肿瘤）。
数据源分层（与 v2 一致，全部带编号来源索引）：
  主证据（MedEvidence 体系）：
    - PubTator 3      文献（PMID + 实体标注）      → pt_query
    - ClinicalTrials  临床试验（NCT）              → ct_cond + ct_term（cond 锚定病种，防跑偏）
    - OpenTargets     靶点-疾病-药物（含临床阶段）  → genes
  补充：
    - Tavily          新闻/会议报道（仅作补充，明确标注）→ news_queries

每个主题的 AI 结论强制引用上述来源编号，构建时做引用校验（防幻觉编号）。
"""

TOPICS = [
    {
        "id": "ped_all",
        "title": "儿童急性淋巴细胞白血病（ALL）：免疫与靶向治疗进展",
        "subtitle": "Pediatric ALL — immunotherapy and targeted approaches",
        "genes": ["CD19", "CD22", "ABL1", "KMT2A"],
        "pt_query": "pediatric acute lymphoblastic leukemia blinatumomab CAR-T inotuzumab",
        "news_queries": [
            "儿童 急性淋巴细胞白血病 CAR-T 双抗 进展",
            "pediatric ALL blinatumomab CAR-T 2026",
            "childhood acute lymphoblastic leukemia immunotherapy trial results",
        ],
        "ct_cond": "Acute Lymphoblastic Leukemia",
        "ct_term": "(pediatric OR child OR childhood) AND (CAR-T OR blinatumomab OR inotuzumab OR targeted)",
    },
    {
        "id": "ped_aml",
        "title": "儿童急性髓系白血病（AML）与髓系肿瘤靶向治疗",
        "subtitle": "Pediatric AML — menin, FLT3 and KMT2A-directed therapy",
        "genes": ["FLT3", "KMT2A", "NPM1", "IDH1", "IDH2"],
        "pt_query": "pediatric acute myeloid leukemia menin inhibitor FLT3 KMT2A",
        "news_queries": [
            "儿童 急性髓系白血病 靶向治疗 menin 抑制剂",
            "pediatric AML menin inhibitor revumenib 2026",
            "childhood acute myeloid leukemia targeted therapy trial",
        ],
        "ct_cond": "Acute Myeloid Leukemia",
        "ct_term": "(pediatric OR child OR childhood) AND (menin OR FLT3 OR KMT2A OR targeted)",
    },
    {
        "id": "lymphoma",
        "title": "淋巴瘤与霍奇金淋巴瘤：双抗、ADC 与免疫检查点",
        "subtitle": "Lymphoma and Hodgkin lymphoma — bispecifics, ADCs, checkpoint blockade",
        "genes": ["TNFRSF8", "PDCD1", "MS4A1", "ALK"],
        "pt_query": "lymphoma bispecific antibody CD30 ADC PD-1 Hodgkin",
        "news_queries": [
            "淋巴瘤 双特异性抗体 ADC 进展 2026",
            "lymphoma bispecific antibody CD30 ADC results 2026",
            "霍奇金淋巴瘤 PD-1 治疗 进展",
        ],
        "ct_cond": "Lymphoma",
        "ct_term": "bispecific OR CD30 OR PD-1 OR antibody-drug conjugate",
    },
    {
        "id": "car_t",
        "title": "细胞治疗与移植：CAR-T、双抗及并发症管理",
        "subtitle": "CAR-T, bispecifics and complication management in hematologic malignancy",
        "genes": ["CD19", "TNFRSF17", "GPRC5D", "CD22"],
        "pt_query": "CAR-T chimeric antigen receptor cytokine release syndrome hematologic malignancy",
        "news_queries": [
            "CAR-T 细胞治疗 血液肿瘤 进展 2026",
            "CAR-T cytokine release syndrome management 2026",
            "双特异性抗体 血液肿瘤 临床 数据 2026",
        ],
        "ct_cond": "Hematologic Neoplasms",
        "ct_term": "CAR-T OR chimeric antigen receptor OR bispecific antibody",
    },
]


# ═══════════════════════ 年度学术会议库（血液肿瘤/儿童肿瘤） ═══════════════════════
# 设计说明：
#   - 每年每个大会一条；build 时自动生成"会议速递"主题卡（关键试验结果表 + 会议报道汇总）。
#   - anchor_ym 是会议内容所属年月：时间筛选按它整卡纳入/排除。
#   - 历史会议（距今超过 refresh_after_days）直接复用最近归档，不重复抓取，节省额度。
#   - expected_trials 可选（缺口定向补搜成本较高，建议只给当期最大的会）。
CONFERENCES = [
    {
        "id": "conf_ash_2026",
        "title": "ASH 2026 会议速递（美国血液学会）",
        "subtitle": "ASH 2026 new drug efficacy trial reports",
        "anchor_ym": "2026-12",
        "news_queries": [
            "ASH 2026 关键试验 结果 血液肿瘤",
            "ASH 2026 late-breaking abstracts leukemia lymphoma myeloma",
            "ASH 2026 CAR-T bispecific trial results",
            "ASH 2026 儿童 血液肿瘤 数据",
        ],
        "news_cap": 14,
        "news_days": 150,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": False,
        "paper_source": "pubmed",
        "pubmed_query": (
            '(ASH 2026[All Fields]) AND (leukemia[Title/Abstract] OR lymphoma[Title/Abstract] OR myeloma[Title/Abstract] OR "CAR-T"[Title/Abstract])'
        ),
        "papers_display": 8,
        "papers_search": 16,
        "refresh_after_days": 200,
    },
    {
        "id": "conf_eha_2026",
        "title": "EHA 2026 会议速递（欧洲血液学会）",
        "subtitle": "EHA 2026 new drug efficacy trial reports",
        "anchor_ym": "2026-06",
        "news_queries": [
            "EHA 2026 关键试验 结果 血液肿瘤",
            "EHA 2026 congress leukemia lymphoma results",
            "EHA 2026 CAR-T bispecific data",
        ],
        "news_cap": 12,
        "news_days": 210,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": False,
        "paper_source": "pubmed",
        "pubmed_query": (
            '(EHA 2026[All Fields]) AND (leukemia OR lymphoma OR myeloma)'
        ),
        "papers_display": 8,
        "papers_search": 16,
        "refresh_after_days": 200,
    },
    {
        "id": "conf_siop_2026",
        "title": "SIOP 2026 会议速递（国际儿童肿瘤学会）",
        "subtitle": "SIOP 2026 pediatric oncology trial reports",
        "anchor_ym": "2026-10",
        "news_queries": [
            "SIOP 2026 儿童 肿瘤 关键 结果",
            "SIOP 2026 pediatric oncology congress results",
            "SIOP 2026 childhood leukemia trial data",
        ],
        "news_cap": 12,
        "news_days": 150,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": False,
        "paper_source": "pubmed",
        "pubmed_query": (
            '(SIOP 2026[All Fields]) AND (pediatric OR childhood OR paediatric OR "children")'
        ),
        "papers_display": 8,
        "papers_search": 16,
        "refresh_after_days": 200,
    },
    {
        "id": "conf_aspho_2026",
        "title": "ASPHO 2026 会议速递（美国儿童血液肿瘤学会）",
        "subtitle": "ASPHO 2026 pediatric hematology-oncology reports",
        "anchor_ym": "2026-05",
        "news_queries": [
            "ASPHO 2026 儿童 血液肿瘤 结果",
            "ASPHO 2026 pediatric hematology oncology abstracts",
            "ASPHO 2026 childhood leukemia results",
        ],
        "news_cap": 10,
        "news_days": 240,
        "extract_key_trials": True,
        "skip_trials": True,
        "no_papers": False,
        "paper_source": "pubmed",
        "pubmed_query": (
            '(ASPHO 2026[All Fields]) AND (pediatric OR childhood OR "children")'
        ),
        "papers_display": 8,
        "papers_search": 16,
        "refresh_after_days": 200,
    },
]


DASHBOARD = {
    "title": "血液肿瘤（含儿童）诊疗情报",
    "subtitle": "MedEvidence 证据体系为主 · 全文来源索引 · Tavily 新闻补充 · 重点：儿童血液肿瘤",
    "author": "AImednews",
    # 署名与许可（CC BY-NC 4.0 要求随生成物传播，勿删）
    "attribution": "© 2026 Chris Lou · CC BY-NC 4.0 非商业许可 · "
                   "引用请注明出处 · loujiacheng1986@foxmail.com",
    "default_days": 21,
    "search_depth": "advanced",   # Tavily: basic=1 credit/次, advanced=2 credits/次
    "top_news_per_topic": 5,      # Tavily 为补充源，数量受控
    "max_trials_per_topic": 8,
    "max_papers_display": 6,      # 展示篇数（检索更多后按年份取最新）
    "max_papers_search": 12,
}