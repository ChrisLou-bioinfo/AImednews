#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
肺癌诊疗情报 Dashboard — 本地 Web 服务器（纯 Python 标准库，无第三方依赖）。

功能：
  - GET /            → 前端页面 webapp/index.html
  - GET /api/data    → 合并数据 JSON
      · 历史归档：output/dashboards/*/data.json（文献/新闻/靶点/AI 解读/来源索引，
        跨全部归档按 PMID/URL/NCT 去重合并，支撑按月/按年回看）
      · 实时试验：ClinicalTrials.gov v2 API 拉取富字段试验（入组数、地点、干预、
        日期、摘要、设计等），刷新页面即可拿到最新数据
  - 缓存 TTL 默认 120 秒；?refresh=1 强制重新拉取（失败时回退缓存）

用法：
  python3 webapp/server.py                # http://localhost:8899
  python3 webapp/server.py --port 9000
  python3 webapp/server.py --no-browser   # 不自动打开浏览器
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from news import config  # noqa: E402  TOPICS / DASHBOARD

WEBAPP_DIR = ROOT / "webapp"
ARCHIVE_DIR = ROOT / "output" / "dashboards"
INDEX_HTML = WEBAPP_DIR / "index.html"

# ── ClinicalTrials.gov v2 富字段（已逐一验证有效）──
CT_FIELDS = ",".join([
    "NCTId", "BriefTitle", "OfficialTitle", "OverallStatus", "Phase", "StudyType",
    "Condition", "InterventionName", "InterventionType", "LeadSponsorName",
    "LeadSponsorClass", "CollaboratorName", "LocationCity", "LocationState",
    "LocationCountry", "LocationFacility", "EnrollmentCount", "EnrollmentType",
    "StartDate", "PrimaryCompletionDate", "CompletionDate", "StudyFirstPostDate",
    "StudyFirstSubmitDate", "BriefSummary", "Sex", "MinimumAge", "MaximumAge",
    "WhyStopped", "DesignAllocation", "DesignInterventionModel",
])
CT_PAGE_SIZE = 50  # 每主题拉取的试验条数（CT.gov 匹配数可上千，展示最新 50）

ST_CN = {
    "RECRUITING": "招募中", "ACTIVE_NOT_RECRUITING": "进行中(不再招募)",
    "ENROLLING_BY_INVITATION": "邀请入组", "NOT_YET_RECRUITING": "尚未开始",
    "COMPLETED": "已完成", "TERMINATED": "已终止", "WITHDRAWN": "已撤回",
    "SUSPENDED": "已暂停", "AVAILABLE": "可用", "NO_LONGER_AVAILABLE": "不可用",
    "APPROVED_FOR_MARKETING": "已获批",
}
PHASE_CN = {"PHASE1": "I期", "PHASE2": "II期", "PHASE3": "III期",
            "PHASE4": "IV期", "NA": "不适用", "EARLY1": "I期(早期)"}

ISO_RE = re.compile(r"(\d{4})(?:[-/](\d{1,2}))?")


def parse_ym(v):
    """从 CT.gov 日期（dict{date,type} 或字符串）提取 (year:int, month:int|None)。"""
    if isinstance(v, dict):
        v = v.get("date") or ""
    m = ISO_RE.search(str(v or ""))
    if not m:
        return (None, None)
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else None)


def _http_get_json(url, timeout=30, retries=2):
    """带双路径回退的 GET：先走系统代理，失败再试直连（本机代理上游偶发不通）。"""
    import urllib.request
    last = None
    openers = []
    if urllib.request.getproxies():
        openers.append(urllib.request.build_opener())               # 系统代理
    openers.append(urllib.request.build_opener(                     # 直连
        urllib.request.ProxyHandler({})))
    for i in range(retries + 1):
        for op in openers:
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "AImednews-dashboard/1.0"})
                with op.open(req, timeout=timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                last = e
        if i < retries:
            time.sleep(1.5 * (i + 1))
    raise last


# ═══════════════════════ 实时试验采集（富字段） ═══════════════════════

def fetch_topic_trials(tp):
    """拉取一个主题的临床试验，返回 (trials, total_count)。

    主题可设 skip_trials（如会议速递主题）；缺 ct_cond/ct_term 时同样跳过，
    返回 ([], None)，由调用方按"无实时数据"处理而不是报错。
    """
    from urllib.parse import urlencode
    cond = tp.get("ct_cond")
    term = tp.get("ct_term")
    if tp.get("skip_trials") or not (cond or term):
        return [], None
    qs = urlencode({
        "query.cond": cond or "",
        "query.term": term or "",
        "pageSize": CT_PAGE_SIZE,
        "format": "json",
        "countTotal": "true",
        "sort": "StudyFirstSubmitDate:desc",
        "fields": CT_FIELDS,
    })
    data = _http_get_json(f"https://clinicaltrials.gov/api/v2/studies?{qs}")
    total = data.get("totalCount")
    out = []
    for st in data.get("studies", []):
        p = st.get("protocolSection") or {}
        ident = p.get("identificationModule") or {}
        sm = p.get("statusModule") or {}
        dm = p.get("designModule") or {}
        sp = p.get("sponsorCollaboratorsModule") or {}
        cl = p.get("contactsLocationsModule") or {}
        ar = p.get("armsInterventionsModule") or {}
        el = p.get("eligibilityModule") or {}
        nct = ident.get("nctId")
        if not nct:
            continue

        locations = cl.get("locations") or []
        countries, cities, facilities = [], [], 0
        seen_c, seen_ci = set(), set()
        for loc in locations:
            facilities += 1
            c = loc.get("country") or ""
            if c and c not in seen_c:
                seen_c.add(c)
                countries.append(c)
            ci = loc.get("city") or ""
            if ci and (ci, c) not in seen_ci:
                seen_ci.add((ci, c))
                cities.append(f"{ci}{'·' + c if c else ''}")

        interventions = []
        seen_iv = set()
        for iv in ar.get("interventions") or []:
            nm = iv.get("name")
            if nm and nm.lower() not in seen_iv:
                seen_iv.add(nm.lower())
                interventions.append({"name": nm, "type": iv.get("type") or ""})

        status = sm.get("overallStatus") or ""
        start = sm.get("startDateStruct") or sm.get("startDate") or ""
        phases = [PHASE_CN.get(x, x) for x in (dm.get("phases") or [])]
        sy, smo = parse_ym(start)
        _, pmo = parse_ym(sm.get("primaryCompletionDateStruct")
                          or sm.get("primaryCompletionDate"))
        ages = " / ".join(x for x in (el.get("minimumAge"), el.get("maximumAge")) if x)

        out.append({
            "nct": nct,
            "title": ident.get("briefTitle") or "",
            "official_title": ident.get("officialTitle") or "",
            "status": status,
            "status_cn": ST_CN.get(status, status),
            "phase": phases,
            "study_type": dm.get("studyType") or "",
            "conditions": ident.get("conditions") or [],
            "interventions": interventions[:8],
            "sponsor": (sp.get("leadSponsor") or {}).get("name") or "",
            "sponsor_class": (sp.get("leadSponsor") or {}).get("class") or "",
            "collaborators": [c.get("name") for c in (sp.get("collaborators") or [])
                              if c.get("name")][:6],
            "n_locations": facilities,
            "countries": countries,
            "cities": cities[:6],
            "enrollment": dm.get("enrollmentInfo", {}).get("count")
            if isinstance(dm.get("enrollmentInfo"), dict) else dm.get("enrollmentInfo"),
            "start_date": (start.get("date") if isinstance(start, dict) else start) or "",
            "completion": _date_str(sm.get("completionDateStruct")
                                   or sm.get("completionDate")),
            "primary_completion": _date_str(sm.get("primaryCompletionDateStruct")
                                            or sm.get("primaryCompletionDate")),
            "first_post": sm.get("studyFirstPostDateStruct", {}).get("date", "") \
            if isinstance(sm.get("studyFirstPostDateStruct"), dict)
            else (sm.get("studyFirstPostDate") or ""),
            "submit_date": sm.get("studyFirstSubmitDate") or "",
            "summary": (p.get("descriptionModule") or {}).get("briefSummary") or "",
            "sex": el.get("sex") or "",
            "ages": ages,
            "allocation": ((dm.get("designInfo") or {}).get("allocation") or ""),
            "model": ((dm.get("designInfo") or {}).get("interventionModel") or ""),
            "why_stopped": sm.get("whyStopped") or "",
            "year": sy, "month": smo, "pmonth": pmo,
            "source": "live",
        })
    return out, total


def _date_str(v):
    if isinstance(v, dict):
        return v.get("date") or ""
    return v or ""


# ═══════════════════════ DeepSeek（问答专题） ═══════════════════════

def load_project_env():
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_project_env()

LLM_ENV_KEYS = ("DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_API_KEY")


def mask_key(k):
    k = str(k or "")
    if not k:
        return ""
    return (k[:6] + "…" + k[-4:]) if len(k) > 12 else "******"


def llm_config_json():
    return {"base_url": ENV.get("DEEPSEEK_BASE_URL", ""),
            "model": ENV.get("DEEPSEEK_MODEL", ""),
            "key_masked": mask_key(ENV.get("DEEPSEEK_API_KEY")),
            "has_key": bool(ENV.get("DEEPSEEK_API_KEY"))}


def persist_llm_env():
    """把 DEEPSEEK_* 三项写回 .env（保留其余行），重启后仍生效。"""
    f = ROOT / ".env"
    lines, seen = [], set()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            k = s.split("=", 1)[0].strip() if ("=" in s and not s.startswith("#")) else None
            if k in LLM_ENV_KEYS:
                if k not in seen:
                    lines.append(f"{k}={ENV.get(k, '')}")
                    seen.add(k)
                continue
            lines.append(line)
    for k in LLM_ENV_KEYS:
        if k not in seen:
            lines.append(f"{k}={ENV.get(k, '')}")
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Gemini 生图（figure-gen 同款 cometapi 通道，带磁盘缓存）──

FIGURE_ENV = {}
_fg = pathlib.Path.home() / ".claude" / "skills" / "figure-gen" / ".env"
if _fg.exists():
    for _line in _fg.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            FIGURE_ENV[_k.strip()] = _v.strip()

FIG_CACHE = ROOT / "output" / "webapp" / "figures"


def gemini_image(prompt):
    """调 cometapi gemini-3-pro-image-preview 生图，返回 (png_bytes, cached)。"""
    import base64
    import hashlib
    import urllib.request
    FIG_CACHE.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]
    png = FIG_CACHE / (cache_key + ".png")
    if png.exists():
        return png.read_bytes(), True
    endpoint = FIGURE_ENV.get("COMETAPI_ENDPOINT")
    api_key = FIGURE_ENV.get("COMETAPI_KEY")
    if not endpoint or not api_key:
        raise RuntimeError("未配置 COMETAPI_KEY/ENDPOINT（~/.claude/skills/figure-gen/.env）")
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    b64 = None
    try:
        for part in data["candidates"][0]["content"]["parts"]:
            d = part.get("inlineData") or {}
            if d.get("data"):
                b64 = d["data"]
                break
    except Exception:  # noqa: BLE001
        pass
    if not b64:
        raise RuntimeError("Gemini 未返回图片: " + json.dumps(data)[:200])
    raw = base64.b64decode(b64)
    png.write_bytes(raw)
    return raw, False


def _deepseek(prompt, max_tokens=1400, temperature=0.3, timeout=120, env=None):
    import urllib.request
    env = env or ENV
    base = env.get("DEEPSEEK_BASE_URL", "").rstrip("/")
    body = json.dumps({
        "model": env.get("DEEPSEEK_MODEL"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature, "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + env.get("DEEPSEEK_API_KEY", ""),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def _extract_terms(question):
    """DeepSeek 抽取检索意图：CT.gov 检索词 + 相关主题 id 列表。"""
    topics_desc = "\n".join(f'- id={t["id"]}  {t["title"]}' for t in _all_topic_cfgs())
    prompt = (
        "你是肺癌临床研究专家。根据用户的医疗问题，产出检索意图，只输出严格 JSON（无其他文字）：\n"
        '{"ct_term": "给 ClinicalTrials.gov query.term 用的英文检索词（3-8 个词，含药物/机制/线数等）",\n'
        ' "topic_ids": ["从下列 id 中选出 0-4 个最相关的主题 id"]}\n\n'
        f"可用主题：\n{topics_desc}\n\n"
        f"用户问题：{question}"
    )
    try:
        raw = _deepseek(prompt, max_tokens=200, temperature=0.1)
        m = re.search(r"\{.*\}", raw, re.S)
        obj = json.loads(m.group(0))
        term = str(obj.get("ct_term") or "")[:200]
        valid = {t["id"] for t in _all_topic_cfgs()}
        tids = [x for x in (obj.get("topic_ids") or []) if x in valid]
        return term, tids
    except Exception as e:  # noqa: BLE001
        print(f"[ask] extract warn: {e}", flush=True)
        return "", [t["id"] for t in _all_topic_cfgs()]


def _fetch_extra_trials(term, n=8):
    """按问题抽取的检索词补拉 CT.gov 试验。"""
    if not term:
        return []
    from urllib.parse import urlencode
    qs = urlencode({
        "query.cond": "Non-Small Cell Lung Cancer",
        "query.term": term,
        "pageSize": n, "format": "json", "countTotal": "false",
        "sort": "StudyFirstSubmitDate:desc", "fields": CT_FIELDS,
    })
    try:
        data = _http_get_json(f"https://clinicaltrials.gov/api/v2/studies?{qs}")
    except Exception as e:  # noqa: BLE001
        print(f"[ask] extra trials warn: {e}", flush=True)
        return []
    tp = {"ct_cond": "Non-Small Cell Lung Cancer", "ct_term": term}
    try:
        trials, _total = fetch_topic_trials(tp)
        return trials
    except Exception as e:  # noqa: BLE001
        print(f"[ask] extra trials parse warn: {e}", flush=True)
        return []


def build_section(question):
    """按医疗问题构建专题：抽取意图 → 补拉试验 → 汇编证据 → DeepSeek 带引用解读。"""
    ct_term, tids = _extract_terms(question)
    trials = _fetch_extra_trials(ct_term)

    payload = HUB.get()  # 复用缓存的全量数据
    papers, news = [], []
    for tp in payload.get("topics", []):
        if tp["id"] in tids:
            papers += tp.get("papers", [])[:3]
            news += tp.get("news", [])[:2]

    refs, details = [], []
    for t in trials:
        refs.append({"kind": "ClinicalTrials.gov",
                     "label": f'{t["nct"]} {t["title"]}（{t["status_cn"]}）',
                     "url": f'https://clinicaltrials.gov/study/{t["nct"]}'})
        summary = (t.get("summary") or "").strip()
        d = f'入组 {t.get("enrollment") if t.get("enrollment") is not None else "未注明"}'
        if summary:
            d += f'；摘要：{summary[:380]}'
        details.append(d)
    for p in papers:
        refs.append({"kind": "PubTator",
                     "label": f'PMID:{p["pmid"]} {p["title"]}（{p.get("year") or "年份未注明"}）',
                     "url": f'https://pubmed.ncbi.nlm.nih.gov/{p["pmid"]}/'})
        details.append(f'摘要：{p["abstract"][:380]}'
                       if (p.get("abstract") or "").strip() else "")
    for n in news:
        refs.append({"kind": "Tavily新闻",
                     "label": f'{(n.get("title") or "")[:110]}（{n.get("published_date") or ""}）',
                     "url": n.get("url") or ""})
        details.append(f'内容：{(n.get("snippet") or "").strip()[:300]}'
                       if (n.get("snippet") or "").strip() else "")

    lines = []
    for i, r in enumerate(refs, 1):
        d = f'；{details[i - 1]}' if details[i - 1] else ""
        lines.append(f'[{i}] {r["kind"]} — {r["label"]}（{r["url"]}）{d}')
    evidence = "\n".join(lines)

    prompt = (
        "你是肺癌领域资深临床专家。请严格基于下方编号证据，回答用户的医疗问题。\n"
        "规则：\n"
        "1) 输出 4-8 条要点，每条以\"- \"开头、单独一行；\n"
        "2) 每条要点末尾用 [编号] 引用支撑它的证据，只能使用证据列表中已有的编号；\n"
        "3) 注重提取和总结研究的核心结论；凡涉及统计结果（如疗效指标 ORR/DCR、"
        "总生存期 OS、无进展生存期 PFS、风险比 HR 及置信区间、p 值、中位生存时间等），"
        "必须把具体数值列出来并附 [编号] 引用；证据中未给出的数值禁止推断或编造；\n"
        "4) 禁止编造编号、数据或结论；证据不足的要点明确写\"证据不足\"；\n"
        "5) 不要开场白和总结语，不要 markdown 符号（如 **）；\n"
        "6) 涉及治疗选择时给出循证、谨慎的表述（本看板仅供专业人员参考）。\n\n"
        f"用户问题：{question}\n\n编号证据列表：\n{evidence}"
    )
    answer, used, invalid = "", [], 0
    try:
        raw = _deepseek(prompt)
        used, invalid = [], 0

        def _repl(m):
            nonlocal invalid
            i = int(m.group(1))
            if 1 <= i <= len(refs):
                used.append(i)
                return f"[{i}]"
            invalid += 1
            return ""

        answer = re.sub(r"\[(\d{1,3})\]", _repl, str(raw or "")).strip()
    except Exception as e:  # noqa: BLE001
        answer = f"AI 解读生成失败：{e}"

    return {"id": "sec_" + str(int(time.time() * 1000)),
            "question": question, "created":
                dt.datetime.now().isoformat(timespec="seconds"),
            "answer": answer, "used": sorted(set(used)), "invalid": invalid,
            "refs": refs, "trials": trials,
            "ct_term": ct_term, "topic_ids": tids}


def build_report(payload):
    """对前端筛选命中的证据生成带编号引用的总结报告（不落盘，随请求生成）。"""
    filters = payload.get("filters") or []
    trials = payload.get("trials") or []
    papers = payload.get("papers") or []
    news = payload.get("news") or []

    refs, lines = [], []
    for t in trials:
        refs.append({"kind": "ClinicalTrials.gov",
                     "label": f'{t.get("nct")} {t.get("title", "")}'
                              f'（{t.get("status_cn") or t.get("status") or ""}）',
                     "url": f'https://clinicaltrials.gov/study/{t.get("nct")}'})
        ivs = "、".join((t.get("ivs") or [])[:6])
        summary = (t.get("summary") or "").strip()
        seg = (f'[{len(refs)}] 试验 {t.get("nct")}《{t.get("title", "")}》'
               f' 状态:{t.get("status_cn") or "-"}'
               f' 分期:{"/".join(t.get("phase") or []) or "-"}'
               f' 申办:{t.get("sponsor") or "-"}'
               f' 开始:{t.get("start_date") or "-"}'
               f' 药物:{ivs or "-"}'
               f' 入组:{t.get("enrollment") if t.get("enrollment") is not None else "-"}')
        if summary:
            seg += f' 摘要：{summary[:380]}'
        lines.append(seg)
    for p in papers:
        refs.append({"kind": "PubTator",
                     "label": f'PMID:{p.get("pmid")} {p.get("title", "")}'
                              f'（{p.get("year") or "年份未注明"}）',
                     "url": f'https://pubmed.ncbi.nlm.nih.gov/{p.get("pmid")}/'})
        seg = (f'[{len(refs)}] 文献 PMID {p.get("pmid")}'
               f'《{p.get("title", "")}》（{p.get("year") or "年份未注明"}）')
        if (p.get("abstract") or "").strip():
            seg += f' 摘要：{p["abstract"][:380]}'
        lines.append(seg)
    for n in news:
        refs.append({"kind": "Tavily新闻",
                     "label": f'{(n.get("title") or "")[:110]}'
                              f'（{n.get("published_date") or ""}）',
                     "url": n.get("url") or ""})
        seg = (f'[{len(refs)}] 新闻《{n.get("title", "")}》'
               f'（{n.get("published_date") or "日期不详"}）')
        if (n.get("snippet") or "").strip():
            seg += f' 内容：{n["snippet"].strip()[:300]}'
        lines.append(seg)

    prompt = (
        "你是肺癌领域资深临床专家。用户在情报看板上按条件筛选出一批证据，"
        "请严格基于下方编号证据，对筛选结果生成总结报告。\n规则：\n"
        "1) 输出 5-8 条要点，每条以\"- \"开头、单独一行；\n"
        "2) 每条要点末尾用 [编号] 引用支撑证据，只能使用证据列表中已有的编号；\n"
        "3) 内容涵盖：整体构成（状态/分期/治疗模式/主要申办方）、重点药物与靶点动向、"
        "值得关注的在研试验（点名 NCT 号）、关键统计结果（疗效/生存期数据）、"
        "文献/新闻的补充信息、证据缺口或随访提示；\n"
        "4) 注重提取和总结研究的核心结论；凡涉及统计结果（如疗效指标 ORR/DCR、"
        "总生存期 OS、无进展生存期 PFS、风险比 HR 及置信区间、p 值、中位生存时间等），"
        "必须把具体数值列出来并附 [编号] 引用；证据中未给出的数值禁止推断或编造；\n"
        "5) 禁止编造编号、数据或结论；证据不足处明确写\"证据不足\"；\n"
        "6) 不要开场白和总结语，不要 markdown 符号；表述循证、谨慎（仅供专业人员参考）。\n\n"
        f"当前筛选条件：{'、'.join(filters) if filters else '无（全部）'}\n"
        f"证据规模：试验 {len(trials)} 项 · 文献 {len(papers)} 篇 · 新闻 {len(news)} 条\n\n"
        "编号证据列表：\n" + "\n".join(lines)
    )
    answer, used, invalid = "", [], 0
    try:
        raw = _deepseek(prompt)

        def _repl(m):
            nonlocal invalid
            i = int(m.group(1))
            if 1 <= i <= len(refs):
                used.append(i)
                return f"[{i}]"
            invalid += 1
            return ""

        answer = re.sub(r"\[(\d{1,3})\]", _repl, str(raw or "")).strip()
    except Exception as e:  # noqa: BLE001
        answer = f"AI 报告生成失败：{e}"

    return {"created": dt.datetime.now().isoformat(timespec="seconds"),
            "filters": filters, "answer": answer,
            "used": sorted(set(used)), "invalid": invalid, "refs": refs}


SECTIONS_LOCK = threading.Lock()
SECTIONS_FILE = ROOT / "output" / "webapp" / "sections.json"


def load_sections():
    with SECTIONS_LOCK:
        if SECTIONS_FILE.exists():
            try:
                return json.loads(SECTIONS_FILE.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return []
        return []


def save_sections(lst):
    with SECTIONS_LOCK:
        SECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECTIONS_FILE.write_text(
            json.dumps(lst[-12:], ensure_ascii=False, indent=1), encoding="utf-8")


# ═══════════════════════ 归档加载与合并 ═══════════════════════

def load_archives():
    """读取全部按日归档 data.json，按日期升序返回 [(yyyymmdd, payload)]。"""
    out = []
    if not ARCHIVE_DIR.exists():
        return out
    for d in sorted(ARCHIVE_DIR.iterdir()):
        f = d / "data.json"
        if d.is_dir() and f.exists():
            try:
                out.append((d.name, json.loads(f.read_text(encoding="utf-8"))))
            except Exception as e:  # noqa: BLE001
                print(f"[archive] 跳过 {d.name}: {e}", flush=True)
    return out


def merge_archives(archives):
    """跨归档合并 papers/news/trials（去重），结构信息取最新归档。"""
    if not archives:
        return None
    latest = archives[-1][1]
    order = {tp["id"]: i for i, tp in enumerate(_all_topic_cfgs())}
    merged = {}
    for tp in latest.get("topics", []):
        merged[tp["id"]] = dict(tp)
        merged[tp["id"]]["papers"] = {p["pmid"]: dict(p) for p in tp.get("papers", [])}
        merged[tp["id"]]["news"] = {n["url"]: dict(n) for n in tp.get("news", []) if n.get("url")}
        merged[tp["id"]]["archive_trials"] = {t["nct"]: dict(t) for t in tp.get("trials", [])}
    for stamp, payload in archives:
        for tp in payload.get("topics", []):
            m = merged.get(tp["id"])
            if not m:
                continue
            for p in tp.get("papers", []):
                m["papers"].setdefault(p["pmid"], dict(p))
            for n in tp.get("news", []):
                if n.get("url"):
                    m["news"].setdefault(n["url"], dict(n))
            for t in tp.get("trials", []):
                old = m["archive_trials"].get(t["nct"])
                if old:
                    for k, v in t.items():
                        if v and not old.get(k):
                            old[k] = v
                else:
                    m["archive_trials"][t["nct"]] = dict(t)
    topics = []
    for tpid in sorted(merged, key=lambda k: order.get(k, 999)):
        m = merged[tpid]
        papers = sorted(m["papers"].values(), key=lambda x: x.get("year") or "",
                        reverse=True)
        news = sorted(m["news"].values(),
                      key=lambda x: x.get("published_date") or "", reverse=True)
        m["papers"], m["news"] = papers, news
        m["trials"] = []  # 由实时层填充
        topics.append(m)
    return {"topics": topics, "latest_generated_at": latest.get("generated_at", ""),
            "global": latest.get("global", {}), "archive_days": [a[0] for a in archives]}


# ═══════════════════════ 导出筛选（按看板当前条件裁剪） ═══════════════════════

# 会议类主题的日期锚点（来自 config，如 ESMO 2026 = 2026-10）
def _all_topic_cfgs():
    """常设主题 + 年度会议库（会议卡同样需要参与排序/锚点/实时拉取配置）。"""
    return list(config.TOPICS) + list(getattr(config, "CONFERENCES", []))


ANCHOR_YM = {t["id"]: str(t.get("anchor_ym") or "")
             for t in _all_topic_cfgs() if t.get("anchor_ym")}


def _anchor_mismatch(tid, year, month):
    """时间筛选与主题日期锚点冲突时返回 True（整卡排除）。"""
    a = ANCHOR_YM.get(tid) or ""
    if not a or (year == "all" and month == "all"):
        return False
    ay = a[:4]
    am = str(int(a[5:7])) if len(a) >= 7 else ""
    if year != "all" and ay != year:
        return True
    if month != "all" and am != month:
        return True
    return False


_ST_GROUP = {
    "recruiting": {"RECRUITING"},
    "active": {"ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION"},
    "soon": {"NOT_YET_RECRUITING", "APPROVED_FOR_MARKETING"},
    "done": {"COMPLETED"},
}


def _ym_of(value):
    m = re.match(r"(\d{4})[-/](\d{1,2})", str(value or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def filter_payload(data, flt):
    """按看板筛选项裁剪导出内容。

    优先使用 sel（前端按看板当前视图算出的精确命中集合，保证"所见即所得"）；
    未提供 sel 时退回按 主题/年月/状态/关键词 的粗筛。
    """
    flt = flt or {}
    sel = flt.get("sel") or {}

    include_conf = bool(flt.get("include_conferences"))
    conf_ids = set(ANCHOR_YM)          # 带日期锚点的即会议类主题

    if sel:
        def allow(mp, tid, *keys):
            allowed = set(mp.get(tid) or [])
            if not allowed:
                return False
            return any(str(k or "") in allowed for k in keys)

        out_topics = []
        for t in (data.get("topics") or []):
            tid = t.get("id")
            if tid not in (sel.get("trials") or {}):
                continue
            if _anchor_mismatch(tid, str(flt.get("year") or "all"),
                                str(flt.get("month") or "all")):
                continue
            if not include_conf and tid in conf_ids:
                continue
            tt = dict(t)
            tt["trials"] = [tr for tr in (t.get("trials") or [])
                            if allow(sel.get("trials") or {}, tid,
                                     tr.get("nct"), tr.get("title"))]
            tt["papers"] = [pp for pp in (t.get("papers") or [])
                            if allow(sel.get("papers") or {}, tid, pp.get("pmid"))]
            tt["news"] = [n for n in (t.get("news") or [])
                          if allow(sel.get("news") or {}, tid, n.get("url"))]
            if not (sel.get("targets") or {}).get(tid):
                tt["targets"] = []
            # 时间筛选生效时，若该主题无任何时间命中项，靶点也不再保留（避免空主题占页）
            time_on = (str(flt.get("year") or "all") != "all"
                       or str(flt.get("month") or "all") != "all")
            anchored = bool(ANCHOR_YM.get(tid))
            if time_on and not anchored and not (tt["trials"] or tt["papers"] or tt["news"]):
                # 无任何时间命中项且无会议锚点：无日期的靶点与会议表一并剔除
                tt["targets"] = []
                tt["key_trials"] = []
            # 会议关键试验：按关键词粗略过滤（无时间字段）
            kw = str(flt.get("q") or "").strip().lower()
            if kw and tt.get("key_trials"):
                tt["key_trials"] = [r for r in tt["key_trials"]
                                    if kw in " ".join(str(r.get(k) or "") for k in
                                                      ("trial", "regimen", "tumor",
                                                       "endpoint", "verdict")).lower()]
            out_topics.append(tt)
        if not out_topics and not include_conf:
            # 剔除会议后为空（例如只筛了某次会议月）：回退保留会议主题，避免空 PPT
            return filter_payload(data, {**flt, "include_conferences": True})
        out = dict(data)
        out["topics"] = out_topics
        return out
    tids = {str(x) for x in (flt.get("topic_ids") or []) if x}
    year = str(flt.get("year") or "all")
    month = str(flt.get("month") or "all")
    status = str(flt.get("status") or "all")
    kw = str(flt.get("q") or "").strip().lower()
    time_on = (year != "all") or (month != "all")

    def ym_ok(y, mo):
        if year != "all" and str(y) != year:
            return False
        if month != "all" and str(mo) != month:
            return False
        return True

    def kw_ok(*vals):
        if not kw:
            return True
        return any(kw in str(v or "").lower() for v in vals)

    out_topics = []
    for t in (data.get("topics") or []):
        if tids and t.get("id") not in tids:
            continue
        if _anchor_mismatch(t.get("id"), year, month):
            continue
        if not include_conf and t.get("id") in conf_ids:
            continue
        tt = dict(t)
        trs = []
        for tr in (t.get("trials") or []):
            y, mo = _ym_of(tr.get("date") or tr.get("submit_date"))
            if time_on and not ym_ok(y, mo):
                continue
            if status != "all" and tr.get("status") not in _ST_GROUP.get(status, set()):
                continue
            if not kw_ok(tr.get("title"), tr.get("nct"), tr.get("sponsor")):
                continue
            trs.append(tr)
        pps = []
        for pp in (t.get("papers") or []):
            if time_on and not ym_ok(pp.get("year"), pp.get("month")):
                continue
            if not kw_ok(pp.get("title"), pp.get("pmid")):
                continue
            pps.append(pp)
        nws = []
        for n in (t.get("news") or []):
            if time_on:
                y, mo = _ym_of(n.get("published_date"))
                if not ym_ok(y, mo):
                    continue
            if not kw_ok(n.get("title"), n.get("url")):
                continue
            nws.append(n)
        if (time_on and not ANCHOR_YM.get(t.get("id"))
                and not (trs or pps or nws)):
            tt["targets"] = []
            tt["key_trials"] = []
        tt["trials"], tt["papers"], tt["news"] = trs, pps, nws
        out_topics.append(tt)
    if not out_topics and not include_conf:
        return filter_payload(data, {**flt, "include_conferences": True})
    out = dict(data)
    out["topics"] = out_topics
    return out


def describe_filter(flt, filtered):
    flt = flt or {}
    parts = []
    tids = flt.get("topic_ids") or []
    if tids:
        parts.append(f"主题 {len(tids)} 个")
    if str(flt.get("year") or "all") != "all":
        parts.append(f"{flt['year']} 年")
    if str(flt.get("month") or "all") != "all":
        parts.append(f"{flt['month']} 月")
    labels = {"recruiting": "招募中", "active": "进行中", "soon": "即将开始",
              "done": "已完成"}
    if str(flt.get("status") or "all") != "all":
        parts.append(f"试验状态 {labels.get(flt['status'], flt['status'])}")
    if flt.get("q"):
        parts.append(f"关键词「{str(flt['q'])[:20]}」")
    if not parts:
        return ""
    n_tr = sum(len(t.get("trials") or []) for t in (filtered.get("topics") or []))
    n_pp = sum(len(t.get("papers") or []) for t in (filtered.get("topics") or []))
    return " · ".join(parts) + f"　（命中：试验 {n_tr} 条 / 文献 {n_pp} 篇；本 PPT 仅含命中内容）"


# ═══════════════════════ 数据中心（缓存 + 合并） ═══════════════════════

class DataHub:
    def __init__(self, ttl=120):
        self.ttl = ttl
        self.lock = threading.Lock()
        self.cache = None
        self.fetched_at = 0.0
        self.errors = []

    def get(self, force=False):
        now = time.time()
        with self.lock:
            fresh = self.cache is not None and (now - self.fetched_at) < self.ttl
            if not force and fresh:
                return self.cache
        # 归档（本地，快）
        base = merge_archives(load_archives())
        topics = base["topics"] if base else []
        # 注入会议主题的日期锚点，供前端时间筛选与导出共用同一规则
        for tp in topics:
            cfg_tp = next((c for c in _all_topic_cfgs() if c["id"] == tp.get("id")), None)
            if cfg_tp and cfg_tp.get("anchor_ym"):
                tp["anchor_ym"] = cfg_tp["anchor_ym"]
        errors = []
        live_counts, total_counts = {}, {}

        # 实时试验（并行拉取四个主题）
        def work(tp):
            cfg_tp = next((c for c in _all_topic_cfgs() if c["id"] == tp["id"]), None)
            if cfg_tp is None or cfg_tp.get("skip_trials") or not cfg_tp.get("ct_cond"):
                return tp["id"], [], None
            try:
                trs, total = fetch_topic_trials(cfg_tp)
                return tp["id"], trs, total
            except Exception as e:  # noqa: BLE001
                errors.append(f"{tp['id']}: {e}")
                return tp["id"], [], None

        fetched = {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            for tid, trs, total in ex.map(work, topics):
                fetched[tid] = trs
                if total is not None:
                    total_counts[tid] = total

        for tp in topics:
            live = fetched.get(tp["id"], [])
            live_ncts = {t["nct"] for t in live}
            extra = []
            for nct, t in tp.pop("archive_trials", {}).items():
                if nct not in live_ncts:
                    sy, smo = parse_ym(t.get("date") or t.get("start_date"))
                    t = dict(t)
                    t.update({"source": "archive", "year": sy, "month": smo,
                              "interventions": [], "conditions": [], "countries": [],
                              "cities": [], "collaborators": [], "summary": "",
                              "n_locations": 0, "study_type": "", "enrollment": None})
                    extra.append(t)
            tp["trials"] = sorted(
                live + extra,
                key=lambda t: (t.get("submit_date") or t.get("date") or ""), reverse=True)
            live_counts[tp["id"]] = len(live)

        payload = {
            "server_time": dt.datetime.now().isoformat(timespec="seconds"),
            "trials_fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "live": not errors,
            "errors": errors,
            "live_counts": live_counts,
            "ct_total_counts": total_counts,
            "archive_days": base["archive_days"] if base else [],
            "latest_generated_at": base["latest_generated_at"] if base else "",
            "global": base.get("global") or {} if base else {},
            "topics": topics,
        }
        with self.lock:
            self.cache = payload
            self.fetched_at = time.time()
        return payload


HUB = DataHub(ttl=60)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 精简日志
        print(f"[http] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                self._send(200, "text/html; charset=utf-8",
                           INDEX_HTML.read_bytes())
            except FileNotFoundError:
                self._send(404, "text/plain; charset=utf-8", b"index.html missing")
        elif u.path.startswith("/assets/"):
            name = pathlib.Path(u.path).name  # 防路径穿越，仅取文件名
            f = WEBAPP_DIR / "assets" / name
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                    ".svg": "image/svg+xml", ".webp": "image/webp",
                    ".css": "text/css; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8"}.get(f.suffix.lower())
            if mime and f.exists():
                self._send(200, mime, f.read_bytes())
            else:
                self._send(404, "text/plain; charset=utf-8", b"asset not found")
        elif u.path == "/api/sections":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(load_sections(), ensure_ascii=False).encode("utf-8"))
        elif u.path == "/api/data":
            q = parse_qs(u.query)
            force = q.get("refresh", ["0"])[0] in ("1", "true")
            try:
                data = HUB.get(force=force)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(data, ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                self._send(500, "application/json; charset=utf-8",
                           json.dumps({"error": str(e)}).encode("utf-8"))
        elif u.path == "/api/pptx":
            q = parse_qs(u.query)
            force = q.get("refresh", ["0"])[0] in ("1", "true")
            try:
                data = HUB.get(force=force)
                sys.path.insert(0, str(WEBAPP_DIR))
                from ppt_deck import build_pptx
                blob = build_pptx(data)
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
                name = f"AImednews-NSCLC-{stamp}.pptx"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(blob)
            except Exception as e:  # noqa: BLE001
                self._send(500, "application/json; charset=utf-8",
                           json.dumps({"error": str(e)}).encode("utf-8"))
        elif u.path == "/api/llm/config":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(llm_config_json(), ensure_ascii=False).encode("utf-8"))
        elif u.path == "/api/health":
            self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path not in ("/api/ask", "/api/sections/delete", "/api/report",
                          "/api/deck/preview", "/api/llm/config", "/api/llm/test",
                          "/api/figure", "/api/pptx"):
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            self._send(400, "application/json; charset=utf-8",
                       b'{"error":"invalid json body"}')
            return

        if u.path == "/api/pptx":
            try:
                data = HUB.get(force=bool(body.get("refresh")))
                include_conf = bool(body.get("include_conferences"))
                filtered = filter_payload(data, body)
                sys.path.insert(0, str(WEBAPP_DIR))
                from ppt_deck import build_pptx
                blob = build_pptx(filtered,
                                  flt_desc=describe_filter(body, filtered),
                                  exclude_conf=not include_conf)
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
                name = f"AImednews-NSCLC-{stamp}.pptx"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(blob)
            except Exception as e:  # noqa: BLE001
                self._send(500, "application/json; charset=utf-8",
                           json.dumps({"error": str(e)}).encode("utf-8"))
            return
        if u.path == "/api/deck/preview":
            name = re.sub(r"[^a-zA-Z0-9_-]", "", str(body.get("name") or ""))[:24]
            f = ROOT / "output" / "webapp" / f"preview_deck{name}.html"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(body.get("html") or ""), encoding="utf-8")
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"ok": True, "saved": str(f)}).encode("utf-8"))
            return

        if u.path == "/api/figure":
            import base64
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                self._send(400, "application/json; charset=utf-8",
                           b'{"error":"prompt required"}')
                return
            try:
                raw, cached = gemini_image(prompt)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"ok": True, "cached": cached,
                                       "data_url": "data:image/png;base64,"
                                       + base64.b64encode(raw).decode()},
                                      ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"ok": False, "error": str(e)},
                                      ensure_ascii=False).encode("utf-8"))
            return

        if u.path == "/api/llm/config":
            for bk, ek in (("base_url", "DEEPSEEK_BASE_URL"),
                           ("model", "DEEPSEEK_MODEL"),
                           ("api_key", "DEEPSEEK_API_KEY")):
                val = str(body.get(bk) or "").strip()
                if val:  # 留空 = 不修改
                    ENV[ek] = val
            try:
                if body.get("persist"):
                    persist_llm_env()
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(llm_config_json(), ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                self._send(500, "application/json; charset=utf-8",
                           json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if u.path == "/api/llm/test":
            env2 = dict(ENV)  # 临时配置（不落盘、不影响运行时），可测未保存的值
            for bk, ek in (("base_url", "DEEPSEEK_BASE_URL"),
                           ("model", "DEEPSEEK_MODEL"),
                           ("api_key", "DEEPSEEK_API_KEY")):
                val = str(body.get(bk) or "").strip()
                if val:
                    env2[ek] = val
            t0 = time.time()
            try:
                reply = _deepseek("只回复两个字：正常", max_tokens=20,
                                  temperature=0, timeout=30, env=env2)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"ok": True, "model": ENV.get("DEEPSEEK_MODEL", ""),
                                       "latency_ms": int((time.time() - t0) * 1000),
                                       "reply": (reply or "").strip()[:20]},
                                      ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"ok": False, "error": str(e)},
                                      ensure_ascii=False).encode("utf-8"))
            return

        if u.path == "/api/sections/delete":
            sid = str(body.get("id") or "")
            lst = [s for s in load_sections() if s.get("id") != sid]
            save_sections(lst)
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(lst, ensure_ascii=False).encode("utf-8"))
            return

        if u.path == "/api/report":
            try:
                rep = build_report(body)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(rep, ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                self._send(500, "application/json; charset=utf-8",
                           json.dumps({"error": str(e)}).encode("utf-8"))
            return

        question = str(body.get("question") or "").strip()
        if not question:
            self._send(400, "application/json; charset=utf-8",
                       b'{"error":"question required"}')
            return
        try:
            sec = build_section(question)
            replace_id = str(body.get("id") or "")
            lst = load_sections()
            if replace_id:
                lst = [s for s in lst if s.get("id") != replace_id]
            lst.append(sec)
            save_sections(lst)
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(lst, ensure_ascii=False).encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._send(500, "application/json; charset=utf-8",
                       json.dumps({"error": str(e)}).encode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description="肺癌诊疗情报 Dashboard Web 服务器")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not INDEX_HTML.exists():
        print(f"[error] 缺少 {INDEX_HTML}", file=sys.stderr)
        sys.exit(2)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"[server] 肺癌诊疗情报 Dashboard → {url}")
    print(f"[server] 归档目录: {ARCHIVE_DIR}")
    print(f"[server] Ctrl+C 停止")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 已停止")


if __name__ == "__main__":
    main()
