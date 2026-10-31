# -*- coding: utf-8 -*-
"""
肺癌 EGFR/MET NSCLC 科研情报看板 v2 —— 每日构建器。

数据分层：
  主证据（MedEvidence 体系，直接复用 medevidence 项目工具层采集，全部带编号来源索引）：
    - tools.pubtator      → PubTator 3 文献（PMID + 实体标注）
    - tools.opentargets   → 靶点-疾病-药物（含最高临床阶段）
    - ClinicalTrials v2   → 临床试验（query.cond 锚定病种 + query.term，同 medevidence/tools/clinicaltrials 端点）
  补充：
    - Tavily 新闻（明确标注"补充来源"，数量受控）

核心约束：
  - 每条证据挂来源编号 [n]；AI 结论强制内联引用，构建时做引用校验（越界编号剔除，防幻觉）。
  - 图表为服务端生成（SVG donut + CSS bar），无 CDN 依赖，离线可开。
  - 交互：全局搜索过滤 / 试验状态筛选 / 主题折叠 / 展开全部 / 返回顶部。

用法：
  .venv/bin/python news/build_dashboard.py --days 7 --synth
"""
import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from tavily import TavilyClient

ROOT = pathlib.Path(__file__).resolve().parent.parent

# MedEvidence 工具层（PubTator 3 / OpenTargets 采集）是可选外部依赖。
# 默认假设与本项目同级目录；也可用环境变量 MEDEX_PATH 指定其 project 目录。
# 未安装时文献/靶点区块会缺失，其余功能不受影响。
MEDEX_PATH = os.environ.get("MEDEX_PATH") or str(
    ROOT.parent / "medevidence" / "medevidence_deploy" / "project"
)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "news"))
if pathlib.Path(MEDEX_PATH).is_dir():
    sys.path.insert(0, MEDEX_PATH)

from news import config  # noqa: E402

load_dotenv(ROOT / ".env")

DASH_DIR = ROOT / "output" / "dashboards"

# ── 网络健壮性：socket 超时 + DNS 解析超时兜底 + 带重试的 HTTP 会话 ──
import socket  # noqa: E402
socket.setdefaulttimeout(25)

import concurrent.futures as _cf  # noqa: E402
_orig_getaddrinfo = socket.getaddrinfo


def _timed_getaddrinfo(*args, **kwargs):
    if "timeout" in kwargs:
        return _orig_getaddrinfo(*args, **kwargs)
    try:
        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_orig_getaddrinfo, *args, **kwargs).result(timeout=8)
    except _cf.TimeoutError:
        raise socket.gaierror("DNS lookup timed out")


socket.getaddrinfo = _timed_getaddrinfo

import requests  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402
try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None


def _mounted_session(total=3, backoff=1.5):
    s = requests.Session()
    if Retry is not None:
        retry = Retry(total=total, backoff_factor=backoff,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET", "POST"], raise_on_status=False)
        ad = HTTPAdapter(max_retries=retry)
        s.mount("https://", ad)
        s.mount("http://", ad)
    return s


HTTP = _mounted_session()


def _with_retry(fn, tries=3, delay=1.5):
    import time
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                import time as _t
                _t.sleep(delay * (i + 1))
    raise last


def _log(msg):
    print(msg, flush=True)


# ── MedEvidence 工具层（PubTator 3 / OpenTargets）──
try:
    import tools.pubtator as pt  # noqa: E402
    import tools.opentargets as ot  # noqa: E402
    MEDEX_OK = True
except Exception as _e:  # pragma: no cover
    pt = None
    ot = None
    MEDEX_OK = False
    _MEDEX_ERR = str(_e)


# ═══════════════════════ 来源登记簿 ═══════════════════════

class SourceBook:
    """每个主题一个：所有证据/新闻在此登记，拿到全局唯一编号 [n]。"""

    def __init__(self):
        self.items = []

    def add(self, kind, label, url="", detail=""):
        self.items.append({"n": len(self.items) + 1, "kind": kind,
                           "label": str(label)[:300], "url": url,
                           "detail": str(detail or "")[:420]})
        return len(self.items)

    def block(self):
        lines = []
        for s in self.items:
            u = f"（{s['url']}）" if s["url"] else ""
            d = f"；内容: {s['detail']}" if s.get("detail") else ""
            lines.append(f"[{s['n']}] {s['kind']} — {s['label']}{u}{d}")
        return "\n".join(lines)


# ═══════════════════════ 工具函数 ═══════════════════════

ST_CN = {
    "RECRUITING": "招募中", "ACTIVE_NOT_RECRUITING": "进行中",
    "ENROLLING_BY_INVITATION": "邀请入组", "NOT_YET_RECRUITING": "即将开始",
    "COMPLETED": "已完成", "TERMINATED": "已终止", "WITHDRAWN": "已撤回",
    "SUSPENDED": "暂停", "APPROVED_FOR_MARKETING": "已获批",
}
PHASE_CN = {"PHASE1": "I期", "PHASE2": "II期", "PHASE3": "III期",
            "PHASE4": "IV期", "NA": "不适用"}
ACTIVE_ST = {"ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION"}
SOON_ST = {"NOT_YET_RECRUITING", "APPROVED_FOR_MARKETING"}


def stage_rank(s):
    """OpenTargets maxClinicalStage 形如 PHASE_3 / APPROVAL / PHASE_1。"""
    s = (s or "").upper()
    if "APPROVAL" in s or "APPROVED" in s:
        return 6
    if re.search(r"PHASE[\s_]*(IV|4)\b", s):
        return 5
    if re.search(r"PHASE[\s_]*(III|3)\b", s):
        return 4
    if re.search(r"PHASE[\s_]*(II|2)\b", s):
        return 3
    if re.search(r"PHASE[\s_]*(I|1)\b", s):
        return 2
    low = s.lower()
    if "preclinical" in low or "discovery" in low:
        return 1
    return 0


def stage_cn(s):
    return STAGE_CN[stage_rank(s)]


STAGE_CN = {6: "已获批", 5: "IV期", 4: "III期", 3: "II期", 2: "I期",
            1: "临床前", 0: "阶段未注明"}


def trial_tier(st):
    if st == "RECRUITING":
        return 0
    if st in ACTIVE_ST:
        return 1
    if st in SOON_ST:
        return 2
    if st == "COMPLETED":
        return 3
    return 4


def esc(s):
    import html
    return html.escape(str(s or ""))


# ═══════════════════════ 采集器（全部登记来源） ═══════════════════════

def collect_targets_ot(genes, book):
    """OpenTargets：靶点 → 关联疾病 + 候选药物（含最高临床阶段）。"""
    out = []
    if ot is None:
        return out
    for gene in genes:
        try:
            hit = _with_retry(lambda: ot.search_target(gene))
            if not hit:
                continue
            ensembl = hit["id"]
            profile = _with_retry(lambda: ot.get_target_profile(ensembl))
        except Exception as e:
            _log(f"    targets warn({gene}): {e}")
            continue
        diseases = []
        for row in (profile.get("associatedDiseases", {}) or {}).get("rows", []):
            d = row.get("disease", {}) or {}
            if d.get("name"):
                diseases.append({"name": d["name"], "score": row.get("score")})
        drugs = []
        for row in (profile.get("drugAndClinicalCandidates", {}) or {}).get("rows", []):
            dg = row.get("drug", {}) or {}
            nm = dg.get("name")
            if not nm:
                continue
            # medevidence 查询把分期放在 drug.maximumClinicalStage；
            # 兼容 row 上的 maxClinicalStage（自建查询形态）
            stage = row.get("maxClinicalStage") or dg.get("maximumClinicalStage") or ""
            drugs.append({"name": nm, "stage": stage})
        drugs.sort(key=lambda x: (-stage_rank(x["stage"]), x["name"]))
        diseases.sort(key=lambda x: -(x.get("score") or 0))
        dnames = ", ".join(d["name"] for d in diseases[:5])
        unames = ", ".join(f"{d['name']}[{d['stage'] or '?'}]" for d in drugs[:6])
        label = f"{hit.get('name') or gene}（{ensembl}）关联疾病: {dnames}；候选药物: {unames}"
        ref = book.add("OpenTargets", label,
                       f"https://platform.opentargets.org/target/{ensembl}")
        out.append({"gene": gene, "symbol": hit.get("name") or gene,
                    "ensembl": ensembl, "diseases": diseases[:8],
                    "drugs": drugs[:8], "ref": ref})
    return out


def collect_trials(cond, term, per_topic, book):
    """ClinicalTrials.gov v2：query.cond 锚定病种 + query.term，提交日期倒序。"""
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.cond": cond,
        "query.term": term,
        "pageSize": per_topic,
        "format": "json",
        "sort": "StudyFirstSubmitDate:desc",
        "fields": ("NCTId,BriefTitle,OverallStatus,Phase,Condition,"
                   "InterventionName,LeadSponsorName,StudyFirstSubmitDate,"
                   "BriefSummary,EnrollmentCount"),
    }
    try:
        r = HTTP.get(url, params=params, headers={"User-Agent": "AImednews/0.2"},
                     timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _log(f"    trials warn: {e}")
        return []
    out = []
    for st in data.get("studies", []):
        p = st.get("protocolSection") or {}
        ident = p.get("identificationModule") or {}
        sm = p.get("statusModule") or {}
        dm = p.get("designModule") or {}
        sp = p.get("sponsorsCollaboratorsModule") or {}
        nct = ident.get("nctId")
        if not nct:
            continue
        status = sm.get("overallStatus") or ""
        phases = [PHASE_CN.get(x, x) for x in (dm.get("phases") or [])]
        title = ident.get("briefTitle") or ""
        sponsor = (sp.get("leadSponsor") or {}).get("name") or ""
        enroll = dm.get("enrollmentInfo", {}).get("count") \
            if isinstance(dm.get("enrollmentInfo"), dict) else dm.get("enrollmentInfo")
        summary = ((p.get("descriptionModule") or {}).get("briefSummary") or "").strip()
        label = (f"{nct} {title[:90]}（{ST_CN.get(status, status) or '状态未注明'}，"
                 f"{'/'.join(phases) or '期别未注明'}，{sponsor}）")
        detail = (f"入组 {enroll if enroll is not None else '未注明'}；"
                  f"摘要：{summary[:380]}") if summary else \
                 (f"入组 {enroll if enroll is not None else '未注明'}"
                  if enroll is not None else "")
        ref = book.add("ClinicalTrials.gov", label,
                       f"https://clinicaltrials.gov/study/{nct}", detail)
        out.append({"nct": nct, "title": title, "status": status,
                    "status_cn": ST_CN.get(status, status), "phase": phases,
                    "sponsor": sponsor,
                    "date": sm.get("studyFirstSubmitDate") or "", "ref": ref})
    # 双层排序（稳定排序）：先按提交日期倒序，再按活跃度分层 → 同层内日期新的在前
    out.sort(key=lambda t: t["date"], reverse=True)
    out.sort(key=lambda t: trial_tier(t["status"]))
    return out


def _esummary(pmids):
    """PubMed esummary 批量取元数据（出版年月、期刊、标题）。"""
    if not pmids:
        return {}
    try:
        r = HTTP.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                     params={"db": "pubmed", "id": ",".join(map(str, pmids)),
                             "retmode": "json", "tool": "AImednews",
                             "email": "amednews@example.org"}, timeout=30)
        return (r.json().get("result") or {})
    except Exception as e:
        _log(f"    pubdate warn: {e}")
        return {}


_MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _parse_pubdate(s):
    """'2026 Dec 31' / '2026 Aug' / '2026' → (year, month)。"""
    s = s or ""
    m = re.match(r"(\d{4})\s*([A-Za-z]{3})?", s)
    if not m:
        return None, None
    return int(m.group(1)), _MON.get((m.group(2) or "").lower())


def _attach_pubdates(papers):
    """给文献补真实出版年月（前端年月筛选与时间线需要）。"""
    res = _esummary([p.get("pmid") for p in papers if p.get("pmid")])
    for p in papers:
        it = res.get(str(p.get("pmid")))
        if not isinstance(it, dict):
            continue
        pub = it.get("pubdate") or ""
        y, mo = _parse_pubdate(pub)
        if pub:
            p["pubdate"] = pub
        if y:
            p["year"] = str(y)
        if mo:
            p["month"] = mo
        if it.get("fulljournalname"):
            p["journal"] = it["fulljournalname"]
        if not p.get("title") and it.get("title"):
            p["title"] = re.sub(r"<[^>]+>", "", it["title"])[:160]
    return papers


def collect_papers_pubmed(query, book, cfg):
    """PubMed 直检文献（ESMO 会议等专题）：带真实出版年月。"""
    out, parsed = [], []
    n_search = cfg.get("max_papers_search", 12)
    n_show = cfg.get("max_papers_display", 6)
    if not query:
        return out
    try:
        es = _with_retry(lambda: HTTP.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmax": n_search,
                    "sort": "pub_date", "retmode": "json",
                    "tool": "AImednews", "email": "amednews@example.org"},
            timeout=30).json())
        ids = es.get("esearchresult", {}).get("idlist", []) or []
    except Exception as e:
        _log(f"    pubmed warn: {e}")
        return out
    if not ids:
        return out
    parsed = [{"pmid": str(pmid), "title": "", "year": "", "entities": {},
               "abstract": ""} for pmid in ids]
    _attach_pubdates(parsed)
    parsed = [p for p in parsed if p.get("title")]
    parsed.sort(key=lambda x: (x.get("year") or "", x.get("month") or 0), reverse=True)
    out = parsed[:n_show]
    for it in out:
        label = (f"PMID:{it['pmid']} {it['title'][:150]}"
                 f"（{it.get('pubdate') or it.get('year') or '日期未注明'}；"
                 f"{it.get('journal') or '期刊未注明'}）")
        it["ref"] = book.add("PubTator", label,
                             f"https://pubmed.ncbi.nlm.nih.gov/{it['pmid']}/", "")
    return out


def collect_papers(pt_query, book, cfg):
    """PubTator 3：检索 → 实体标注 → 按年份取最新若干篇。"""
    out, parsed = [], []
    if pt is None:
        return out
    n_search = cfg.get("max_papers_search", 12)
    n_show = cfg.get("max_papers_display", 6)
    try:
        pmids = _with_retry(lambda: pt.search_text(pt_query, limit=n_search))
        if not pmids:
            return out
        docs = _with_retry(lambda: pt.export_pmids(pmids))
    except Exception as e:
        _log(f"    papers warn: {e}")
        return out
    for pmid in pmids:
        doc = docs.get(str(pmid))
        if not isinstance(doc, dict):
            continue
        title, year, ents, abstract = "", "", {}, ""
        for passage in doc.get("passages", []) or []:
            if not isinstance(passage, dict):
                continue
            inf = passage.get("infons") or {}
            if inf.get("type") == "title" and not title:
                title = passage.get("text", "")
            if inf.get("type") in ("abstract", "Abstract") and not abstract:
                abstract = (passage.get("text") or "").strip()
            for k in ("year", "date", "pubdate"):
                if not year and inf.get(k):
                    m = re.search(r"\d{4}", str(inf[k]))
                    if m:
                        year = m.group(0)
            for ann in passage.get("annotations", []) or []:
                if not isinstance(ann, dict):
                    continue
                t = (ann.get("infons") or {}).get("type", "other")
                txt = ann.get("text", "")
                if txt:
                    ents.setdefault(t, set()).add(txt)
        parsed.append({"pmid": str(pmid), "title": title[:160], "year": year,
                       "abstract": abstract[:420],
                       "entities": {k: sorted(v)[:6] for k, v in ents.items()}})
    # 先按年份取最新 n_show 篇，再登记来源编号（避免孤儿编号）
    parsed.sort(key=lambda x: x["year"], reverse=True)
    out = parsed[:n_show]
    _attach_pubdates(out)  # 补真实出版年月（供前端年月筛选）
    out.sort(key=lambda x: (x.get("year") or "", x.get("month") or 0), reverse=True)
    for it in out:
        ent_flat = []
        for k in ("Gene", "Disease", "Variant", "Chemical"):
            for v in (it["entities"].get(k) or [])[:3]:
                ent_flat.append(v)
        label = (f"PMID:{it['pmid']} {it['title']}"
                 f"（{it.get('pubdate') or it['year'] or '年份未注明'}；"
                 f"实体: {', '.join(ent_flat[:6]) or '无标注'}）")
        it["ref"] = book.add("PubTator", label,
                             f"https://pubmed.ncbi.nlm.nih.gov/{it['pmid']}/",
                             f"摘要：{it['abstract']}" if it["abstract"] else "")
    return out


def collect_news(tclient, queries, days, cap, depth, book, raw=False):
    """Tavily 新闻（补充来源）。raw=True 时抓正文，供会议关键试验抽取。"""
    items = []
    for q in queries:
        try:
            r = _with_retry(lambda: tclient.search(
                query=q, search_depth=depth, max_results=cap,
                include_answer=False, include_raw_content=raw, days=days))
        except Exception as e:
            _log(f"    news warn({q[:24]}): {e}")
            continue
        for it in r.get("results", []):
            items.append(it)
    seen, dedup = set(), []
    for it in sorted(items, key=lambda x: x.get("score") or 0, reverse=True):
        u = (it.get("url") or "").lower()
        if not u or u in seen:
            continue
        seen.add(u)
        dedup.append({"title": it.get("title") or "", "url": it.get("url"),
                      "score": it.get("score"),
                      "published_date": it.get("published_date") or "",
                      "snippet": (it.get("content") or "").strip()[:300],
                      "raw": ((it.get("raw_content") or "") if raw else "")[:15000]})
    # 先截断再登记来源编号（避免孤儿编号）
    dedup = dedup[:cap]
    for it in dedup:
        it["ref"] = book.add("Tavily新闻",
                             f'{it["title"][:110]}（{it["published_date"]}）',
                             it["url"],
                             f"内容：{it['snippet']}" if it.get("snippet") else "")
    return dedup


def extract_key_trials(news, max_rows=120, max_sources=15):
    """逐篇从会议报道正文抽取结构化关键试验结果，再合并去重（提高召回）。

    只抽原文明确出现的数字；src 必须是该篇来源编号（防幻觉）。
    """
    cands = [n for n in news if (n.get("raw") or "").strip() and n.get("ref")]
    if not cands:
        return []

    def likely_table(n):
        t = (n.get("raw") or "").lower()
        return any(k in t for k in ("hazard ratio", " hr ", "hr=", "phase iii",
                                    "phase 3", "lba", "95% ci"))

    # 优先"含 HR/III期/LBA"的汇总稿，其次按正文长度
    cands.sort(key=lambda n: (likely_table(n), len(n.get("raw") or "")), reverse=True)
    cands = cands[:max_sources]

    out, seen = [], set()

    def num(v):
        try:
            if v is None or v == "":
                return None
            return float(str(v).replace("%", "").strip())
        except Exception:  # noqa: BLE001
            return None

    for n in cands:
        ref = n["ref"]
        body = (n.get("raw") or "")[:14000]
        prompt = (
            "你是肿瘤学会议报道分析助手。下面是一篇 ESMO 2026 会议报道的正文，来源编号 [" + str(ref) + "]。\n"
            "请抽取其中报告的 III 期/关键注册试验结果，输出**纯 JSON 数组**"
            "（不要解释、不要 markdown 代码块；若本文没有试验结果则输出 []）：\n"
            '[{"endpoint":"总生存|无进展/无事件/无复发生存|客观缓解率|其他",'
            '"regimen":"方案","trial":"试验名","tumor":"瘤种与场景",'
            '"hr":数值或null,"ci_low":数值或null,"ci_high":数值或null,'
            '"n":样本量数值或null,"verdict":"达到主要终点|未达显著/未成熟","src":' + str(ref) + '}]\n'
            "规则：1) 只抽正文明确出现的数字，缺失一律 null，禁止推断；"
            "2) trial 必须是正文出现的试验名；3) src 固定为 " + str(ref) + "；"
            "4) 同一试验同一终点只保留一行；5) 不要臆造正文没有的行。\n\n" + body
        )
        try:
            raw = _deepseek(prompt, max_tokens=1800, temperature=0.1, timeout=90)
        except Exception as e:  # noqa: BLE001
            _log(f"    key_trials warn(ref {ref}): {e}")
            continue
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            continue
        try:
            rows = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            continue
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            trial = str(row.get("trial") or "").strip()
            if not trial:
                continue
            ep = str(row.get("endpoint") or "").strip()
            key = (trial.lower(), ep, str(row.get("hr")))
            if key in seen:
                continue
            seen.add(key)
            nv = num(row.get("n"))
            out.append({"endpoint": ep, "regimen": str(row.get("regimen") or "").strip(),
                        "trial": trial, "tumor": str(row.get("tumor") or "").strip(),
                        "hr": num(row.get("hr")), "ci_low": num(row.get("ci_low")),
                        "ci_high": num(row.get("ci_high")),
                        "n": int(nv) if nv is not None else None,
                        "verdict": str(row.get("verdict") or "").strip(), "src": ref})
            if len(out) >= max_rows:
                return out
    return out


def _norm_trial(x):
    """试验名归一：去掉 / 之后的平台编号、括号内容、空白与标点。"""
    t = str(x or "")
    t = t.split("/")[0]
    t = re.sub(r"[（(].*?[)）]", "", t)
    t = re.sub(r"[\s\-_·]+", "", t).upper()
    return t


_EP_MAP = [
    (("总生存", "overall survival", "os"), "总生存"),
    (("无进展", "无事件", "无复发", "progression", "event-free", "recurrence"), "无进展/无事件/无复发生存"),
    (("客观缓解", "缓解率", "objective response", "orr"), "客观缓解率"),
]


def clean_key_trials(rows, max_rows=90):
    """清洗抽取结果：去噪行、统一字段、同试验同终点保留信息最全的一行。"""
    def ep_norm(e):
        el = str(e or "").lower()
        for keys, label in _EP_MAP:
            if any(k in el for k in keys):
                return label
        return "其他"

    def better(a, b):
        # 评分：有 HR > 有 CI > 有 N
        def sc(r):
            return (3 if r.get("hr") is not None else 0) + \
                   (1 if r.get("ci_low") is not None and r.get("ci_high") is not None else 0) + \
                   (1 if r.get("n") is not None else 0)
        return a if sc(a) >= sc(b) else b

    best = {}
    for r in rows or []:
        ep = ep_norm(r.get("endpoint"))
        trial = str(r.get("trial") or "").strip()
        if not trial:
            continue
        # 去噪：既无 HR 又无 N、且终点归为"其他"的行丢弃
        if r.get("hr") is None and r.get("n") is None and ep == "其他":
            continue
        trial = re.sub(r"\s+", " ", trial.split("/")[0]).strip()
        # 规范化已知写法
        trial = re.sub(r"^(CA017-078|EN-?ERGI[ZS]E)\s+", "", trial, flags=re.I) or trial
        if "ENERGIZE" in trial.upper():
            trial = "ENERGIZE"
        verdict = str(r.get("verdict") or "").strip()
        if "未达" in verdict or "未成熟" in verdict or verdict.lower().startswith("not"):
            verdict = "未达显著/未成熟"
        elif verdict:
            verdict = "达到主要终点"
        item = {"endpoint": ep, "regimen": str(r.get("regimen") or "").strip(),
                "trial": trial, "tumor": str(r.get("tumor") or "").strip(),
                "hr": r.get("hr"), "ci_low": r.get("ci_low"),
                "ci_high": r.get("ci_high"), "n": r.get("n"),
                "verdict": verdict, "src": r.get("src")}
        key = (_norm_trial(trial), ep)
        if key in best:
            best[key] = better(best[key], item)
        else:
            best[key] = item
    out = list(best.values())
    out.sort(key=lambda r: (0 if r["hr"] is not None else 1, -len(r["trial"])))
    return out[:max_rows]


# ═══════════════════════ AI 综合（强制引用 + 校验） ═══════════════════════

def _deepseek(prompt, max_tokens=900, temperature=0.3, timeout=60):
    r = HTTP.post(
        os.getenv("DEEPSEEK_BASE_URL", "").rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
                 "Content-Type": "application/json"},
        json={"model": os.getenv("DEEPSEEK_MODEL"),
              "messages": [{"role": "user", "content": prompt}],
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=timeout)
    r.raise_for_status()
    return (r.json().get("choices", [{}])[0].get("message") or {}).get("content", "")


def synthesize(sources_block, instruction):
    prompt = (
        "你是肿瘤肺癌领域专家。下面给出编号证据列表，请严格基于证据输出中文要点。\n"
        "规则：\n"
        "1) 每条要点以\"- \"开头，单独一行，末尾用 [编号] 引用支撑它的证据；\n"
        "2) 只能使用证据列表中已有的编号，禁止编造编号、数据或结论；\n"
        "3) 注重提取和总结研究的核心结论；凡涉及统计结果（如疗效指标 ORR/DCR、"
        "总生存期 OS、无进展生存期 PFS、风险比 HR 及置信区间、p 值、中位生存时间等），"
        "必须把具体数值列出来并附 [编号] 引用；证据中未给出的数值禁止推断或编造；\n"
        "4) 证据不足时明确写\"证据不足\"；\n"
        "5) 不要开场白、不要总结语、不要使用任何 markdown 符号（如 **）；\n"
        "6) 优先依据 OpenTargets / ClinicalTrials.gov / PubTator 证据，Tavily 新闻仅作背景。\n\n"
        f"任务：{instruction}\n\n编号证据列表：\n{sources_block}"
    )
    try:
        return _deepseek(prompt)
    except Exception as e:
        _log(f"    synth warn: {e}")
        return ""


def validate_citations(text, n_sources):
    """剔除越界/幻觉引用编号，返回 (清洗后文本, 有效引用集合, 剔除数)。"""
    used, invalid = [], 0

    def repl(m):
        nonlocal invalid
        i = int(m.group(1))
        if 1 <= i <= n_sources:
            used.append(i)
            return f"[{i}]"
        invalid += 1
        return ""

    cleaned = re.sub(r"\[(\d{1,3})\]", repl, str(text or ""))
    return cleaned.strip(), sorted(set(used)), invalid


# ═══════════════════════ 渲染 ═══════════════════════

PALETTE = ["#3fb27f", "#58a6ff", "#d29922", "#bc8cff", "#f778ba",
           "#79c0ff", "#ffa657", "#56d364"]


def fmt_rich(text, anchor_prefix):
    """转义 → **粗体**还原 → [n] 引用变锚点链接 → 换行变 <br>。"""
    s = esc(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[(\d{1,3})\]",
               lambda m: f'<a class="cref" href="#{anchor_prefix}{m.group(1)}">[{m.group(1)}]</a>',
               s)
    return s.replace("\n", "<br>")


def donut_svg(data, size=168, stroke=28):
    total = sum(d["value"] for d in data) or 1
    R = (size - stroke) / 2 - 4
    C = 2 * math.pi * R
    cx = cy = size / 2
    segs, acc = [], 0.0
    for i, d in enumerate(data):
        frac = d["value"] / total
        ln = frac * C
        if ln <= 0:
            continue
        col = PALETTE[i % len(PALETTE)]
        segs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{col}" '
            f'stroke-width="{stroke}" stroke-dasharray="{ln:.2f} {C - ln:.2f}" '
            f'stroke-dashoffset="{-acc:.2f}" transform="rotate(-90 {cx} {cy})">'
            f'<title>{esc(d["label"])}: {d["value"]}（{frac * 100:.0f}%）</title></circle>')
        acc += ln
    center = (f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" class="dnum">{total}</text>'
              f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" class="dlab">合计</text>')
    legend = "".join(
        f'<span class="lg"><i style="background:{PALETTE[i % len(PALETTE)]}"></i>'
        f'{esc(d["label"])} · {d["value"]}</span>' for i, d in enumerate(data))
    return (f'<div class="donut"><svg width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">{"".join(segs)}{center}</svg>'
            f'<div class="lgs">{legend}</div></div>')


def bars_html(data):
    mx = max([d["value"] for d in data] + [1])
    rows = []
    for d in data:
        w = round(d["value"] / mx * 100, 1)
        rows.append(
            f'<div class="brow"><span class="blabel" title="{esc(d["label"])}">{esc(d["label"])}</span>'
            f'<div class="btrack"><div class="bfill" style="width:{w}%"></div></div>'
            f'<span class="bval">{d["value"]}</span></div>')
    return '<div class="bars">' + "".join(rows) + "</div>"


def chart_block(title, body, note=""):
    n = f'<div class="cnote">{esc(note)}</div>' if note else ""
    return f'<div class="chart"><div class="ctitle">{esc(title)}</div>{body}{n}</div>'


CHIPS = [("all", "全部"), ("recruiting", "招募中"), ("active", "进行中"),
         ("soon", "即将开始"), ("done", "已完成")]


def render_topic(t):
    tid = t["id"]
    ev_count = len(t["trials"]) + len(t["papers"]) + len(t["targets"])
    parts = [f'<section class="topic" id="{tid}">']
    parts.append(
        f'<div class="topic-h"><h2>{esc(t["title"])}'
        f'<span class="en">{esc(t["subtitle"])}</span></h2>'
        f'<span class="badge">证据 {ev_count} · 来源 {len(t["refs"])}</span></div>')
    parts.append('<div class="body">')

    if t.get("synth"):
        warn = "" if t.get("used") else '<div class="empty">⚠ 本段未附有效引用编号</div>'
        parts.append(f'<div class="synth"><b>AI 关键解读</b>'
                     f'<span class="ai-tag">AI 生成 · 引用见下方来源索引 · 仅供参考</span>'
                     f'<div>{fmt_rich(t["synth"], "r-" + tid + "-")}</div>{warn}</div>')
    # 会议关键试验结果表（AI 从会议报道抽取，逐行带来源编号）
    if t.get("key_trials"):
        th = ('style="border:1px solid #2a3442;padding:5px 8px;font-size:11px;'
              'color:#8b98a9;text-align:left;white-space:nowrap"')
        td = 'style="border:1px solid #2a3442;padding:5px 8px;font-size:12px"'
        parts.append('<details class="refs" open><summary>📊 ESMO 2026 关键注册试验结果（全瘤种 · '
                     + str(len(t["key_trials"])) + ' 行 · AI 从会议报道抽取，数字请以原文为准）</summary>')
        parts.append('<div style="overflow-x:auto;margin:8px 0"><table style="border-collapse:collapse;width:100%">'
                     '<thead><tr>'
                     + "".join('<th ' + th + '>' + h + '</th>' for h in
                               ("终点", "方案", "试验", "瘤种/场景", "HR", "95%CI", "N", "判定", "来源"))
                     + '</tr></thead><tbody>')
        for r in t["key_trials"]:
            ci = (f'{r["ci_low"]:g}–{r["ci_high"]:g}'
                  if r.get("ci_low") is not None and r.get("ci_high") is not None else "—")
            hr = f'{r["hr"]:g}' if r.get("hr") is not None else "—"
            nv = r.get("n") if r.get("n") is not None else "—"
            src = (f'<a class="cref" href="#r-{tid}-{r["src"]}">[{r["src"]}]</a>'
                   if r.get("src") else "—")
            parts.append('<tr>'
                         + f'<td {td}>{esc(r["endpoint"])}</td>'
                         + f'<td {td}>{esc(r["regimen"])}</td>'
                         + f'<td {td}>{esc(r["trial"])}</td>'
                         + f'<td {td}>{esc(r["tumor"])}</td>'
                         + f'<td {td}>{hr}</td><td {td}>{ci}</td><td {td}>{nv}</td>'
                         + f'<td {td}>{esc(r["verdict"])}</td><td {td}>{src}</td>'
                         + '</tr>')
        parts.append('</tbody></table></div></details>')
    parts.append('<div class="cols">')

    # 靶点 / 药物
    parts.append('<div class="block"><b class="sec">🧬 靶点 · 疾病 · 药物（OpenTargets）</b>')
    if not t["targets"]:
        parts.append('<div class="empty">暂无</div>')
    for g in t["targets"]:
        dchips = "".join(f'<span class="tag" title="关联分 {d.get("score") or "?"}">'
                         f'{esc(d["name"])}</span>' for d in g["diseases"][:5])
        uchips = "".join(
            f'<span class="tag st{stage_rank(d["stage"])}" title="{esc(d["stage"])}">'
            f'{esc(d["name"])}<i>{esc(stage_cn(d["stage"]))}</i></span>' for d in g["drugs"][:8])
        parts.append(
            f'<div class="item"><div class="t">'
            f'<a href="https://platform.opentargets.org/target/{esc(g["ensembl"])}" target="_blank">'
            f'{esc(g["symbol"])}</a><span class="src">OpenTargets</span>'
            f'<a class="cref" href="#r-{tid}-{g["ref"]}">[{g["ref"]}]</a></div>'
            f'<div class="s">疾病：{dchips or "—"}</div>'
            f'<div class="s">候选药物：{uchips or "—"}</div></div>')
    parts.append("</div>")

    # 临床试验
    parts.append('<div class="block"><b class="sec">🧪 临床试验（ClinicalTrials.gov）</b>'
                 '<div class="chips">' +
                 "".join(f'<button class="chip{" on" if f == "all" else ""} data-f="{f}">{esc(cn)}</button>'
                         for f, cn in CHIPS) + "</div>")
    if not t["trials"]:
        parts.append('<div class="empty">暂无</div>')
    for tr in t["trials"]:
        ptags = "".join(f'<span class="tag">{esc(x)}</span>' for x in tr["phase"][:3])
        parts.append(
            f'<div class="item" data-st="{esc(tr["status"])}"><div class="t">'
            f'<a href="https://clinicaltrials.gov/study/{esc(tr["nct"])}" target="_blank">'
            f'{esc(tr["title"])}</a><span class="src">ClinicalTrials</span>'
            f'<a class="cref" href="#r-{tid}-{tr["ref"]}">[{tr["ref"]}]</a></div>'
            f'<div class="s">{esc(tr["nct"])} · {esc(tr["status_cn"] or tr["status"])} · {esc(tr["sponsor"])}</div>'
            f'<div class="s">{ptags}</div></div>')
    parts.append("</div>")

    # 文献
    parts.append('<div class="block"><b class="sec">📄 文献（PubTator 3 · 实体标注）</b>')
    if not t["papers"]:
        parts.append('<div class="empty">暂无</div>')
    for pp in t["papers"]:
        echips = "".join(f'<span class="tag">{esc(x)}</span>'
                         for k in ("Gene", "Disease", "Variant", "Chemical")
                         for x in (pp["entities"].get(k) or [])[:2])
        parts.append(
            f'<div class="item"><div class="t">'
            f'<a href="https://pubmed.ncbi.nlm.nih.gov/{esc(pp["pmid"])}/" target="_blank">'
            f'{esc(pp["title"])}</a><span class="src">PubTator</span>'
            f'<a class="cref" href="#r-{tid}-{pp["ref"]}">[{pp["ref"]}]</a></div>'
            f'<div class="s">PMID {esc(pp["pmid"])} · {esc(pp["year"] or "年份未注明")}</div>'
            f'<div class="s">{echips}</div></div>')
    parts.append("</div>")

    # 新闻（补充）
    parts.append('<div class="block"><b class="sec">📰 新闻补充（Tavily · 非证据源）</b>')
    if not t["news"]:
        parts.append('<div class="empty">暂无</div>')
    for n in t["news"]:
        score = f'{n["score"]:.2f}' if isinstance(n.get("score"), (int, float)) else ""
        parts.append(
            f'<div class="item news"><div class="t">'
            f'<a href="{esc(n["url"])}" target="_blank">{esc(n["title"])}</a>'
            f'<span class="src tv">Tavily·补充</span>'
            f'<a class="cref" href="#r-{tid}-{n["ref"]}">[{n["ref"]}]</a></div>'
            f'<div class="s">{esc(n["published_date"])} {("· 相关度 " + score) if score else ""}</div>'
            f'<div class="s">{esc(n["snippet"])}</div></div>')
    parts.append("</div>")

    parts.append("</div>")  # cols

    # 来源索引
    parts.append(f'<details class="refs"><summary>📚 来源索引（{len(t["refs"])} 条）—— 所有结论可溯源</summary><ol>')
    for s in t["refs"]:
        link = f' <a href="{esc(s["url"])}" target="_blank">链接</a>' if s["url"] else ""
        parts.append(f'<li id="r-{tid}-{s["n"]}"><span class="src">{esc(s["kind"])}</span> '
                     f'{esc(s["label"])}{link}</li>')
    parts.append("</ol></details>")
    parts.append("</div></section>")
    return "\n".join(parts)


def render_summary(topics, gsynth, gused, grefs, charts, kpis, now):
    parts = ['<section class="topic" id="overview"><div class="topic-h">'
             '<h2>📊 总览 · 今日情报全景</h2>'
             f'<span class="badge">{kpis["evidence"]} 条证据</span></div><div class="body">']

    parts.append('<div class="kpis">' + "".join(
        f'<div class="kpi"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for k, v in kpis["cards"]) +
        "</div>")

    if gsynth:
        warn = "" if gused else '<div class="empty">⚠ 本段未附有效引用编号</div>'
        parts.append(f'<div class="synth"><b>AI 跨主题总结</b>'
                     f'<span class="ai-tag">AI 生成 · 引用见下方来源索引 · 仅供参考</span>'
                     f'<div>{fmt_rich(gsynth, "g-")}</div>{warn}</div>')
        parts.append(f'<details class="refs" open><summary>📚 总结引用来源（{len(grefs)} 条）</summary><ol>')
        for s in grefs:
            link = f' <a href="{esc(s["url"])}" target="_blank">链接</a>' if s["url"] else ""
            parts.append(f'<li id="g-{s["n"]}"><span class="src">{esc(s["kind"])}</span> '
                         f'{esc(s["label"])}{link}</li>')
        parts.append("</ol></details>")

    parts.append('<div class="charts">')
    parts.append(chart_block("各主题证据条目", bars_html(charts["topics"])))
    parts.append(chart_block("试验状态分布", donut_svg(charts["trial_status"])))
    parts.append(chart_block("试验分期分布", bars_html(charts["phases"]), "按试验数计（一项试验可属多期）"))
    parts.append(chart_block("文献年度分布", bars_html(charts["years"]), "按 PMID 标注年份"))
    parts.append(chart_block("候选药物临床阶段", bars_html(charts["drug_stage"]), "按药物去重"))
    parts.append(chart_block("数据源构成", donut_svg(charts["src_comp"])))
    parts.append("</div>")
    parts.append("</div></section>")
    return "\n".join(parts)


CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--line:#2a3442;--txt:#e6edf3;
--sub:#8b98a9;--accent:#3fb27f;--accent2:#58a6ff;--warn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,
"PingFang SC","Microsoft YaHei",Segoe UI,Roboto,sans-serif;line-height:1.6}
header{padding:24px 32px 16px;border-bottom:1px solid var(--line);
background:linear-gradient(180deg,#11161d,#0d1117);position:sticky;top:0;z-index:9;
backdrop-filter:blur(4px)}
h1{margin:0;font-size:22px}
.sub{color:var(--sub);font-size:13px;margin-top:4px}
.meta{margin-top:10px;font-size:12px;color:var(--sub);display:flex;gap:16px;flex-wrap:wrap;align-items:center}
.meta b{color:var(--accent2)}
.controls{margin-left:auto;display:flex;gap:8px;align-items:center}
#q{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
border-radius:8px;padding:6px 12px;font-size:13px;width:220px;outline:none}
#q:focus{border-color:var(--accent2)}
#expand{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
border-radius:8px;padding:6px 12px;font-size:12px;cursor:pointer}
.container{max-width:1240px;margin:0 auto;padding:20px 24px 70px}
.topic{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:20px 0;overflow:hidden}
.topic-h{padding:14px 22px;background:var(--panel2);border-bottom:1px solid var(--line);
display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none}
.topic-h h2{margin:0;font-size:17px}
.topic-h .en{color:var(--sub);font-size:12px;font-weight:400;margin-left:8px}
.badge{background:var(--accent);color:#04231a;border-radius:20px;padding:2px 12px;font-size:12px;font-weight:700}
.body{padding:16px 22px}
.synth{margin:0 0 14px;padding:12px 18px;background:#13211b;border-left:3px solid var(--accent);
font-size:14px;color:#cfe9dd;border-radius:0 8px 8px 0}
.synth b{color:var(--accent);margin-right:8px}
.ai-tag{float:right;color:var(--sub);font-size:11px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:920px){.cols{grid-template-columns:1fr}}
.block{min-width:0}
.block b.sec{display:block;color:var(--accent2);font-size:13px;margin:8px 0 8px}
.item{padding:9px 12px;background:var(--panel2);border:1px solid var(--line);
border-radius:8px;margin-bottom:8px;font-size:13px}
.item a{color:var(--accent2);text-decoration:none}
.item a:hover{text-decoration:underline}
.item .t{font-weight:600;margin-bottom:2px}
.item .s{color:var(--sub);font-size:12px;margin-top:3px}
.tag{display:inline-block;background:#22314a;color:#9ecbff;border-radius:6px;
padding:1px 7px;font-size:11px;margin:2px 4px 0 0}
.tag i{font-style:normal;color:var(--sub);margin-left:3px}
.tag.st6{background:#1d3a2a;color:#7ee2a8}
.tag.st5,.tag.st4{background:#1f3350;color:#9ecbff}
.src{display:inline-block;background:#2b2440;color:#c8a6ff;border-radius:6px;
padding:0 7px;font-size:10px;margin-left:7px;vertical-align:1px;font-weight:600}
.src.tv{background:#3a2b18;color:#e8b36a}
.cref{color:var(--accent);font-size:11px;margin-left:5px;text-decoration:none;font-weight:700}
.cref:hover{text-decoration:underline}
.chips{margin:2px 0 8px;display:flex;gap:6px;flex-wrap:wrap}
.chip{background:var(--panel);border:1px solid var(--line);color:var(--sub);
border-radius:14px;padding:1px 11px;font-size:11px;cursor:pointer}
.chip.on{background:var(--accent2);border-color:var(--accent2);color:#04121f;font-weight:700}
.refs{margin-top:12px;border-top:1px dashed var(--line);padding-top:8px}
.refs summary{cursor:pointer;color:var(--sub);font-size:12px}
.refs ol{margin:8px 0 0 18px;padding:0;font-size:12px;color:var(--sub)}
.refs li{margin-bottom:5px}
.refs li .src{margin:0 6px 0 0}
.refs a{color:var(--accent2)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
@media(max-width:920px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi{background:var(--panel2);border:1px solid var(--line);border-radius:10px;
padding:10px 14px;text-align:center}
.kpi b{display:block;font-size:20px;color:var(--accent2)}
.kpi span{font-size:11px;color:var(--sub)}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
@media(max-width:920px){.charts{grid-template-columns:1fr}}
.chart{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.ctitle{font-size:13px;color:var(--accent2);margin-bottom:8px;font-weight:700}
.cnote{font-size:11px;color:var(--sub);margin-top:6px}
.donut{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.dnum{font-size:26px;fill:var(--txt);font-weight:700}
.dlab{font-size:11px;fill:var(--sub)}
.lgs{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--sub)}
.lg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px}
.bars{display:flex;flex-direction:column;gap:6px}
.brow{display:grid;grid-template-columns:120px 1fr 36px;gap:8px;align-items:center;font-size:12px}
.blabel{color:var(--sub);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right}
.btrack{background:#0d1117;border-radius:5px;height:14px;overflow:hidden}
.bfill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:5px}
.bval{color:var(--txt);font-weight:700;text-align:right}
#totop{position:fixed;right:18px;bottom:18px;background:var(--panel2);border:1px solid var(--line);
color:var(--txt);border-radius:50%;width:38px;height:38px;cursor:pointer;font-size:16px;display:none}
footer{color:var(--sub);font-size:12px;text-align:center;padding:20px}
.empty{color:var(--sub);font-size:12px;padding:4px 2px}
"""

JS = """
var STMAP={recruiting:["RECRUITING"],active:["ACTIVE_NOT_RECRUITING","ENROLLING_BY_INVITATION"],
soon:["NOT_YET_RECRUITING","APPROVED_FOR_MARKETING"],done:["COMPLETED"]};
function applyFilters(){
  var q=document.getElementById('q').value.trim().toLowerCase();
  document.querySelectorAll('section.topic').forEach(function(sec){
    if(sec.id==='overview'){return;}
    var on=sec.querySelector('.chip.on');
    var f=on?on.getAttribute('data-f'):'all';
    var allow=(f==='all')?null:(STMAP[f]||[]);
    sec.querySelectorAll('.item').forEach(function(it){
      var okQ=!q||it.textContent.toLowerCase().indexOf(q)>=0;
      var okF=true;
      if(allow&&it.hasAttribute('data-st')){okF=allow.indexOf(it.getAttribute('data-st'))>=0;}
      it.style.display=(okQ&&okF)?'':'none';
    });
    sec.querySelectorAll('.block').forEach(function(b){
      var items=[].slice.call(b.querySelectorAll('.item'));
      var vis=items.filter(function(i){return i.style.display!=='none';}).length;
      var note=b.querySelector('.nofit');
      if(items.length&&vis===0){
        if(!note){note=document.createElement('div');note.className='empty nofit';
        note.textContent='（当前筛选/搜索无匹配）';b.appendChild(note);}
        note.style.display='';
      }else if(note){note.style.display='none';}
    });
  });
}
document.querySelectorAll('.chips').forEach(function(g){
  g.querySelectorAll('.chip').forEach(function(c){
    c.addEventListener('click',function(){
      g.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
      c.classList.add('on');applyFilters();
    });
  });
});
document.getElementById('q').addEventListener('input',applyFilters);
document.querySelectorAll('.topic-h').forEach(function(h){
  h.addEventListener('click',function(){
    var b=h.nextElementSibling;
    if(b){b.style.display=(b.style.display==='none')?'':'none';}
  });
});
var expanded=true;
document.getElementById('expand').addEventListener('click',function(){
  expanded=!expanded;
  document.querySelectorAll('.topic > .body, .topic-h + .body').forEach(function(b){
    b.style.display=expanded?'':'none';
  });
  this.textContent=expanded?'收起全部':'展开全部';
});
var tt=document.getElementById('totop');
window.addEventListener('scroll',function(){tt.style.display=window.scrollY>400?'block':'none';});
tt.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});});
"""


def build_charts(topics):
    SHORT = {"egfr_l1_later": "EGFR 一线/后线", "egfr_tp53": "EGFR+TP53",
             "egfr_resistance": "EGFR 耐药", "met_primary": "MET 异常",
             "esmo_congress": "ESMO 2026", "conf_wclc_2026": "WCLC 2026",
             "conf_asco_2026": "ASCO 2026", "conf_aacr_2026": "AACR 2026",
             "conf_esmo_asia_2026": "ESMO Asia 2026"}
    topics_bar = [{"label": SHORT.get(t["id"], t["title"][:12]),
                   "value": len(t["trials"]) + len(t["papers"]) + len(t["targets"])}
                  for t in topics]
    st_cnt, ph_cnt, yr_cnt, drug_stage = {}, {}, {}, {}
    seen_drugs = set()
    src_cnt = {"OpenTargets": 0, "ClinicalTrials.gov": 0, "PubTator": 0, "Tavily新闻": 0}
    for t in topics:
        for s in t["refs"]:
            if s["kind"] in src_cnt:
                src_cnt[s["kind"]] += 1
        for tr in t["trials"]:
            key = ST_CN.get(tr["status"], tr["status"] or "未知")
            grp = ("招募中" if tr["status"] == "RECRUITING"
                   else "进行中" if tr["status"] in ("ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION")
                   else "即将开始" if tr["status"] in SOON_ST
                   else "已完成" if tr["status"] == "COMPLETED" else "其他")
            st_cnt[grp] = st_cnt.get(grp, 0) + 1
            for p in tr["phase"]:
                ph_cnt[p] = ph_cnt.get(p, 0) + 1
        for pp in t["papers"]:
            y = pp["year"] or "未知"
            yr_cnt[y] = yr_cnt.get(y, 0) + 1
        for g in t["targets"]:
            for d in g["drugs"]:
                k = d["name"].lower()
                if k in seen_drugs:
                    continue
                seen_drugs.add(k)
                b = STAGE_CN[stage_rank(d["stage"])]
                drug_stage[b] = drug_stage.get(b, 0) + 1

    st_order = ["招募中", "进行中", "即将开始", "已完成", "其他"]
    trial_status = [{"label": k, "value": st_cnt.get(k, 0)} for k in st_order
                    if st_cnt.get(k, 0) > 0] or [{"label": "暂无", "value": 1}]
    ph_order = ["I期", "II期", "III期", "IV期", "不适用"]
    phases = [{"label": k, "value": ph_cnt[k]} for k in ph_order if ph_cnt.get(k)]
    years = [{"label": k, "value": yr_cnt[k]}
             for k in (sorted([y for y in yr_cnt if y.isdigit()], reverse=True) +
                       (["未知"] if "未知" in yr_cnt else []))[:8]]
    ds_order = ["已获批", "IV期", "III期", "II期", "I期", "临床前", "阶段未注明"]
    drug_stage_l = [{"label": k, "value": drug_stage[k]} for k in ds_order if drug_stage.get(k)]
    src_comp = [{"label": k, "value": v} for k, v in src_cnt.items() if v > 0]

    return {
        "topics": topics_bar,
        "trial_status": trial_status,
        "phases": phases or [{"label": "暂无", "value": 1}],
        "years": years or [{"label": "暂无", "value": 1}],
        "drug_stage": drug_stage_l or [{"label": "暂无", "value": 1}],
        "src_comp": src_comp or [{"label": "暂无", "value": 1}],
    }


# ═══════════════════════ 单主题处理 ═══════════════════════

ARCH_DIR = ROOT / "output" / "dashboards"


def _conference_topic(conf):
    """把会议库条目转成可采集的主题配置（会议类：不抓试验/文献，只抓报道+抽关键试验）。"""
    t = dict(conf)
    t.setdefault("genes", [])
    t.setdefault("skip_trials", True)
    t.setdefault("no_papers", True)
    t.setdefault("extract_key_trials", True)
    t.setdefault("news_cap", 12)
    t.setdefault("news_days", 180)
    t.setdefault("subtitle", f"{conf.get('title', '')} · new drug efficacy trial reports")
    t["_conference"] = True
    return t


def _conf_stale(tp):
    """会议内容是否已过保鲜期（过期则复用归档，不重复抓取）。"""
    from datetime import date
    ym = str(tp.get("anchor_ym") or "")
    if len(ym) < 7 or not tp.get("refresh_after_days"):
        return False
    y, m = int(ym[:4]), int(ym[5:7])
    conf_end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return (date.today() - conf_end).days > int(tp["refresh_after_days"])


def _cached_topic(tid):
    """从最近归档里取同名主题（用于历史会议沉淀复用）。"""
    if not ARCH_DIR.exists():
        return None
    for d in sorted([x for x in ARCH_DIR.iterdir() if x.is_dir() and x.name.isdigit()],
                    reverse=True):
        f = d / "data.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for t in (data.get("topics") or []):
            if t.get("id") == tid and (t.get("key_trials") or t.get("news")):
                return t
    return None


def _process_topic(tp, args, key, cfg):
    book = SourceBook()
    tclient = None if args.no_news else TavilyClient(api_key=key)
    _log(f"  ▶ {tp['title']}")

    targets = [] if args.no_targets else collect_targets_ot(tp["genes"], book)
    pcfg = dict(cfg)
    if tp.get("papers_display"):
        pcfg["max_papers_display"] = int(tp["papers_display"])
    if tp.get("papers_search"):
        pcfg["max_papers_search"] = int(tp["papers_search"])
    trials = [] if (args.no_trials or tp.get("skip_trials")) else collect_trials(
        tp["ct_cond"], tp["ct_term"], cfg.get("max_trials_per_topic", 8), book)
    if args.no_lit or tp.get("no_papers"):
        papers = []
    elif tp.get("paper_source") == "pubmed":
        papers = collect_papers_pubmed(tp.get("pubmed_query", ""), book, pcfg)
    else:
        papers = collect_papers(tp.get("pt_query", ""), book, pcfg)
    news_days = tp.get("news_days", args.days)
    news_cap = int(tp.get("news_cap", cfg.get("top_news_per_topic", 5)))
    news = [] if args.no_news or tclient is None else collect_news(
        tclient, tp["news_queries"], news_days, news_cap,
        cfg.get("search_depth", "advanced"), book,
        raw=bool(tp.get("extract_key_trials")))
    key_trials = extract_key_trials(news) if tp.get("extract_key_trials") else []
    # ── 缺口补齐：对配置中列出但未抽到的关键试验，按试验名定向补搜并抽取 ──
    if key_trials and tp.get("expected_trials") and tclient is not None and not args.no_news:
        have = {_norm_trial(r.get("trial")) for r in key_trials}
        missing = [t for t in tp["expected_trials"]
                   if not any(_norm_trial(t) in h or h in _norm_trial(t)
                              for h in have if h)][:10]
        if missing:
            _log(f"      缺口补齐：{len(missing)} 个试验待补 → {missing}")
            extra_news = []
            for tname in missing:
                try:
                    rr = _with_retry(lambda: tclient.search(
                        query=f"ESMO 2026 {tname} results", search_depth="basic",
                        max_results=2, include_answer=False,
                        include_raw_content=True, days=240))
                except Exception as e:  # noqa: BLE001
                    _log(f"        gap warn({tname}): {e}")
                    continue
                for it in rr.get("results", []):
                    ttl = it.get("title") or ""
                    url = it.get("url") or ""
                    ref = book.add("Tavily新闻", f"{ttl[:110]}（ESMO 2026 · 缺口补齐）", url,
                                   f"内容：{(it.get('content') or '')[:200]}")
                    extra_news.append({"title": ttl, "url": url, "score": it.get("score"),
                                       "published_date": it.get("published_date") or "",
                                       "snippet": (it.get("content") or "")[:300],
                                       "raw": (it.get("raw_content") or "")[:15000],
                                       "ref": ref})
            if extra_news:
                news.extend(extra_news)
                added = extract_key_trials(extra_news)
                seen_keys = {(r["trial"].lower(), r["endpoint"], str(r["hr"]))
                             for r in key_trials}
                for r in added:
                    k = (r["trial"].lower(), r["endpoint"], str(r["hr"]))
                    if k not in seen_keys:
                        seen_keys.add(k)
                        key_trials.append(r)
                _log(f"      缺口补齐：新增 {len(key_trials)} 行（总）")
    if key_trials:
        key_trials = clean_key_trials(key_trials)
        _log(f"      关键试验清洗后：{len(key_trials)} 行"
             f"（含HR {sum(1 for r in key_trials if r['hr'] is not None)}）")

    synth, used, invalid = "", [], 0
    if args.synth and book.items:
        instruction = f"围绕主题「{tp['title']}」，总结当前治疗格局与新进展、在研方向。"
        raw = synthesize(book.block(), instruction)
        synth, used, invalid = validate_citations(raw, len(book.items))
    _log(f"      靶点{len(targets)} 试验{len(trials)} 文献{len(papers)} 新闻{len(news)} "
         f"关键试验{len(key_trials)} 来源{len(book.items)} "
         f"引用{len(used)}({'剔' + str(invalid) if invalid else 'OK'})")

    return {"id": tp["id"], "title": tp["title"], "subtitle": tp["subtitle"],
            "anchor_ym": tp.get("anchor_ym") or "",
            "targets": targets, "trials": trials, "papers": papers, "news": news,
            "key_trials": key_trials,
            "refs": book.items, "synth": synth, "used": used, "invalid": invalid}


# ═══════════════════════ 主流程 ═══════════════════════

def main():
    p = argparse.ArgumentParser(description="Build NSCLC intelligence dashboard v2")
    p.add_argument("--days", type=int, default=config.DASHBOARD.get("default_days", 21))
    p.add_argument("--synth", action="store_true", help="生成 DeepSeek 关键解读（强制引用）")
    p.add_argument("--no-news", action="store_true")
    p.add_argument("--no-trials", action="store_true")
    p.add_argument("--no-lit", action="store_true")
    p.add_argument("--no-targets", action="store_true")
    p.add_argument("--jobs", type=int, default=min(4, len(config.TOPICS)))
    args = p.parse_args()

    from tavily import TavilyClient
    key = os.getenv("TAVILY_API_KEY")
    if not key and not args.no_news:
        _log("缺少 TAVILY_API_KEY（--no-news 可跳过新闻）")
        sys.exit(2)
    if not MEDEX_OK:
        _log(f"⚠ medevidence 工具层不可用：{_MEDEX_ERR}（文献/靶点将缺失）")

    cfg = config.DASHBOARD
    _log(f"[build v2] 主题={len(config.TOPICS)} days={args.days} "
         f"depth={cfg.get('search_depth')} synth={'Y' if args.synth else '-'} "
         f"medevidence={'OK' if MEDEX_OK else 'MISSING'}")

    # 采集清单 = 常设主题 + 年度会议库
    topic_cfgs = list(config.TOPICS) + [_conference_topic(c)
                                        for c in getattr(config, "CONFERENCES", [])]

    # 历史会议：过了保鲜期且有归档 → 直接复用，不再联网抓取（省钱、稳定）
    pre_topics, run_cfgs = [], []
    for tp in topic_cfgs:
        if tp.get("_conference") and _conf_stale(tp):
            cached = _cached_topic(tp["id"])
            if cached:
                _log(f"  ↺ 复用归档（历史会议）：{tp.get('title')}")
                pre_topics.append(cached)
                continue
        run_cfgs.append(tp)

    if len(run_cfgs) > 1 and args.jobs > 1:
        with ThreadPoolExecutor(max_workers=min(args.jobs, len(run_cfgs))) as ex:
            futs = [ex.submit(_process_topic, tp, args, key, cfg) for tp in run_cfgs]
            topics = []
            for f in futs:
                try:
                    topics.append(f.result())
                except Exception as e:  # noqa: BLE001
                    _log(f"    topic error: {e}")
    else:
        topics = [_process_topic(tp, args, key, cfg) for tp in run_cfgs]
    topics.extend(pre_topics)

    order = {tp["id"]: i for i, tp in enumerate(topic_cfgs)}
    topics.sort(key=lambda t: order.get(t["id"], 999))

    # 跨主题总结：全局来源登记（主题前缀），同样强制引用 + 校验
    gsynth, gused, grefs = "", [], []
    if args.synth:
        gbook = SourceBook()
        for t in topics:
            for s in t["refs"]:
                gbook.add(s["kind"], f"【{t['title'][:16]}】{s['label']}", s["url"])
        if gbook.items:
            raw = synthesize(gbook.block(),
                             "做跨主题总结：4-6 条要点，概括四个主题各自的最新格局与共同趋势，"
                             "指出对临床实践的意义。")
            gsynth, gused, _inv = validate_citations(raw, len(gbook.items))
            grefs = gbook.items
            _log(f"  跨主题总结：引用 {len(gused)} / 来源 {len(grefs)}")

    n_trials = sum(len(t["trials"]) for t in topics)
    n_recruiting = sum(1 for t in topics for tr in t["trials"] if tr["status"] == "RECRUITING")
    n_papers = sum(len(t["papers"]) for t in topics)
    n_targets = sum(len(t["targets"]) for t in topics)
    n_news = sum(len(t["news"]) for t in topics)
    n_refs = sum(len(t["refs"]) for t in topics)
    evidence = n_trials + n_papers + n_targets
    kpis = {"evidence": evidence, "cards": [
        ("主题", len(topics)), ("证据条目", evidence),
        ("试验(招募中)", f"{n_recruiting}/{n_trials}"), ("文献", n_papers),
        ("靶点", n_targets), ("新闻补充", n_news), ("来源索引", n_refs),
        ("更新", dt.datetime.now().strftime("%m-%d %H:%M")),
    ]}
    charts = build_charts(topics)

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    body = render_summary(topics, gsynth, gused, grefs, charts, kpis, now) + "\n" + \
        "\n".join(render_topic(t) for t in topics)
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(cfg['title'])}</title><style>{CSS}</style></head><body>
<header><h1>{esc(cfg['title'])}</h1>
<div class="sub">{esc(cfg['subtitle'])}</div>
<div class="meta"><span>生成：<b>{esc(now)}</b></span>
<span>证据主体：<b>PubTator 3 · ClinicalTrials.gov · OpenTargets</b>（MedEvidence 体系）</span>
<span>新闻：<b>Tavily（补充）</b></span>
<span>结论均带 <b>[n]</b> 来源编号</span>
<span class="controls"><input id="q" placeholder="🔍 全局搜索证据…">
<button id="expand">收起全部</button></span></div></header>
<div class="container">{body}</div>
<footer>{esc(cfg['author'])} · 证据：PubTator 3 / ClinicalTrials.gov / OpenTargets · 新闻补充：Tavily ·
AI 生成内容仅供参考，请以原始来源为准 · 点击主题标题折叠<br>{esc(cfg.get('attribution', ''))}</footer>
<button id="totop">↑</button>
<script>{JS}</script></body></html>"""

    stamp = dt.datetime.now().strftime("%Y%m%d")
    out_dir = DASH_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    latest = DASH_DIR / "latest" / "index.html"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(html, encoding="utf-8")

    payload = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"),
               "params": {"days": args.days, "depth": cfg.get("search_depth"),
                          "synth": bool(args.synth)},
               "kpis": kpis, "charts": charts, "topics": topics,
               "global": {"synth": gsynth, "used": gused, "refs": grefs}}
    json_path = out_dir / "data.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _log(f"\n[done] HTML: {html_path}")
    _log(f"       latest: {latest}")
    _log(f"       data: {json_path}")


if __name__ == "__main__":
    main()
