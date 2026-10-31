# -*- coding: utf-8 -*-
"""AImednews —— 导出真实 PowerPoint (.pptx)。

设计目标（对标 DSH 直接生成的 PPT 观感）：
  - 16:9 宽屏、统一版式与配色、页眉页脚、页码；
  - 原生可编辑图表（PowerPoint 里可改数据/样式），不是图片；
  - 原生表格（ESMO 关键试验结果，可编辑）；
  - 每页标注数据来源与免责声明，AI 结论带 [n] 引用编号。

用法：
    from ppt_deck import build_pptx
    blob: bytes = build_pptx(payload_dict)   # payload 同 /api/data
"""
from __future__ import annotations

import datetime as dt
import io
import pathlib
import re
from typing import Any, Dict, List

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

# ── 版式常量 ──────────────────────────────────────────────
SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.62)
CONTENT_W = SLIDE_W - 2 * MARGIN

C_NAVY = RGBColor(0x0B, 0x1F, 0x33)      # 深底
C_NAVY2 = RGBColor(0x12, 0x2E, 0x4A)     # 次深底
C_INK = RGBColor(0x14, 0x22, 0x30)       # 浅底正文
C_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
C_MUTED = RGBColor(0x9F, 0xB2, 0xC6)
C_MUTED_D = RGBColor(0x5D, 0x71, 0x86)
C_GREEN = RGBColor(0x2F, 0xBF, 0x8F)
C_BLUE = RGBColor(0x4C, 0x9A, 0xFF)
C_AMBER = RGBColor(0xE8, 0xA3, 0x3D)
C_RED = RGBColor(0xE5, 0x6A, 0x5E)
C_LINE = RGBColor(0xD8, 0xE0, 0xE8)
C_PANEL = RGBColor(0xF3, 0xF6, 0xF9)

PALETTE = [C_GREEN, C_BLUE, C_AMBER, RGBColor(0x9B, 0x8C, 0xE8),
           RGBColor(0xE5, 0x6A, 0x5E), RGBColor(0x4F, 0xC3, 0xD6)]

ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
TOPIC_FIG = {"egfr_l1_later": "FigureTopic1.jpg", "egfr_tp53": "FigureTopic2.jpg",
             "egfr_resistance": "FigureTopic3.jpg", "met_primary": "FigureTopic4.jpg"}

FONT_CN = "Arial Unicode MS"   # 实测：中英混排在 LibreOffice/PowerPoint 下不丢字
FONT_EN = "Arial Unicode MS"

TODAY = dt.datetime.now().strftime("%Y-%m-%d")


# ── 低层工具 ──────────────────────────────────────────────
def _ea_font(run, name: str) -> None:
    """设置东亚字体。a:ea 必须紧跟 a:latin（OOXML 顺序），否则会错解字形（实测丢字）。"""
    rPr = run._r.get_or_add_rPr()
    latin = rPr.find(qn("a:latin"))
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        if latin is not None:
            latin.addnext(ea)
        else:
            rPr.append(ea)
    ea.set("typeface", name)
    cs = rPr.find(qn("a:cs"))
    if cs is None:
        cs = rPr.makeelement(qn("a:cs"), {})
        ea.addnext(cs)
    cs.set("typeface", name)


def _font(run, size: float, bold: bool = False, color: RGBColor = C_WHITE,
          name: str = FONT_CN) -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = name
    _ea_font(run, name)


def _bg(slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _rect(slide, left, top, width, height, color: RGBColor, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp


def _text(slide, left, top, width, height, text: str, size: float = 16,
          bold: bool = False, color: RGBColor = C_WHITE, align=PP_ALIGN.LEFT,
          anchor=MSO_ANCHOR.TOP, line_spacing: float | None = None,
          space_after: float | None = None):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.02)
    tf.margin_top = tf.margin_bottom = Inches(0.01)
    lines = str(text).split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if line_spacing:
            p.line_spacing = line_spacing
        if space_after is not None:
            p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = line
        _font(r, size, bold, color)
    return tb


def _bullets(slide, left, top, width, height, items: List[str], size: float = 15,
             color: RGBColor = C_WHITE, bullet_color: RGBColor = C_GREEN,
             max_items: int = 8):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.02)
    for i, it in enumerate(items[:max_items]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(6)
        r0 = p.add_run()
        r0.text = "▪ "
        _font(r0, size, True, bullet_color)
        r = p.add_run()
        r.text = it
        _font(r, size, False, color)
    return tb


def _header(slide, kicker: str, title: str, dark: bool = True,
            page: str = "") -> None:
    """内容页页眉：小节标签 + 标题 + 右上角页码。"""
    tcol = C_GREEN if dark else C_GREEN
    _text(slide, MARGIN, Inches(0.42), CONTENT_W, Inches(0.3), kicker.upper(),
          11, True, tcol)
    _text(slide, MARGIN, Inches(0.70), CONTENT_W - Inches(1.0), Inches(0.62),
          _clean(title, 34), 24, True, C_WHITE if dark else C_INK)
    if page:
        _text(slide, SLIDE_W - MARGIN - Inches(0.9), Inches(0.46),
              Inches(0.9), Inches(0.3), page, 11, False,
              C_MUTED if dark else C_MUTED_D, PP_ALIGN.RIGHT)
    # 分隔线
    ln = slide.shapes.add_connector(1, MARGIN, Inches(1.45),
                                    SLIDE_W - MARGIN, Inches(1.45))
    ln.line.color.rgb = C_LINE if not dark else RGBColor(0x2A, 0x44, 0x60)
    ln.line.width = Pt(1)


def _footer(slide, text: str, dark: bool = True) -> None:
    _text(slide, MARGIN, SLIDE_H - Inches(0.46), CONTENT_W, Inches(0.3),
          text, 9, False, C_MUTED if dark else C_MUTED_D)


def _kpi_card(slide, left, top, w, h, value: str, label: str,
              accent: RGBColor = C_GREEN) -> None:
    _rect(slide, left, top, w, h, C_NAVY2, RGBColor(0x24, 0x3F, 0x5C))
    _rect(slide, left, top, Inches(0.05), h, accent)
    _text(slide, left + Inches(0.18), top + Inches(0.14), w - Inches(0.3),
          Inches(0.62), value, 26, True, C_WHITE)
    _text(slide, left + Inches(0.18), top + h - Inches(0.44), w - Inches(0.3),
          Inches(0.32), label, 11, False, C_MUTED)


def _clean(txt: str, limit: int | None = None) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", str(txt or ""))
    s = re.sub(r"[ \t]+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1] + "…"
    return s


def _synth_bullets(synth: str, limit: int = 6, each: int = 118) -> List[str]:
    """把 AI 解读整理成要点列表（保留 [n] 引用编号）。"""
    out = []
    for raw in str(synth or "").split("\n"):
        s = _clean(raw)
        s = re.sub(r"^[-•·*]\s*", "", s)
        if len(s) < 8:
            continue
        out.append(_clean(s, each))
        if len(out) >= limit:
            break
    return out


# ── 图表 ──────────────────────────────────────────────────
def _chart(slide, kind, left, top, w, h, labels, values, title="",
           legend=True, colors=None):
    data = CategoryChartData()
    data.categories = labels
    data.add_series("计数", values)
    gf = slide.shapes.add_chart(kind, left, top, w, h, data)
    ch = gf.chart
    ch.font.size = Pt(10)
    ch.font.name = FONT_CN
    ch.font.color.rgb = C_WHITE
    if title:
        ch.has_title = True
        ch.chart_title.text_frame.text = title
        for p in ch.chart_title.text_frame.paragraphs:
            for r in p.runs:
                _font(r, 12, True, C_WHITE)
    ch.has_legend = legend
    if legend:
        ch.legend.position = XL_LEGEND_POSITION.RIGHT
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(9)
        ch.legend.font.color.rgb = C_MUTED
    try:
        plot = ch.plots[0]
        plot.has_data_labels = True
        plot.data_labels.font.size = Pt(9)
        plot.data_labels.font.color.rgb = C_WHITE
        if kind in (XL_CHART_TYPE.DOUGHNUT, XL_CHART_TYPE.PIE):
            plot.data_labels.position = XL_LABEL_POSITION.CENTER
        else:
            plot.gap_width = 40
    except Exception:  # noqa: BLE001
        pass
    series = ch.series[0]
    if kind != XL_CHART_TYPE.DOUGHNUT:
        try:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = C_GREEN
        except Exception:  # noqa: BLE001
            pass
    if colors:
        for i, c in enumerate(colors[: len(values)]):
            try:
                pt = series.points[i]
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = c
                pt.format.line.color.rgb = C_NAVY
            except Exception:  # noqa: BLE001
                pass
    return gf


# ── 数据聚合 ──────────────────────────────────────────────
def _agg(payload: Dict[str, Any]) -> Dict[str, Any]:
    topics = payload.get("topics") or []
    st, ph, yr, src, drugs = {}, {}, {}, {}, {}
    for t in topics:
        for s in (t.get("refs") or []):
            k = s.get("kind") or "其他"
            src[k] = src.get(k, 0) + 1
        for tr in (t.get("trials") or []):
            label = {"RECRUITING": "招募中", "ACTIVE_NOT_RECRUITING": "进行中",
                     "ENROLLING_BY_INVITATION": "邀请入组",
                     "NOT_YET_RECRUITING": "即将开始", "COMPLETED": "已完成",
                     "TERMINATED": "已终止", "WITHDRAWN": "已撤回"}.get(
                         tr.get("status") or "", "其他")
            st[label] = st.get(label, 0) + 1
            for p in (tr.get("phase") or []):
                ph[p] = ph.get(p, 0) + 1
        for p in (t.get("papers") or []):
            y = str(p.get("year") or "未知")
            yr[y] = yr.get(y, 0) + 1
        for g in (t.get("targets") or []):
            for d in (g.get("drugs") or []):
                stage = d.get("stage") or ""
                nu = re.sub(r"[^0-9IVX]", "", stage.upper()) or "未注明"
                drugs[nu] = drugs.get(nu, 0) + 1

    def top(d, n=6):
        return sorted(d.items(), key=lambda kv: -kv[1])[:n]

    return {"status": top(st), "phases": top(ph), "years": top(yr),
            "sources": top(src), "drugs": top(drugs),
            "n_topics": len(topics),
            "n_trials": sum(len(t.get("trials") or []) for t in topics),
            "n_recruiting": sum(1 for t in topics for tr in (t.get("trials") or [])
                                if tr.get("status") == "RECRUITING"),
            "n_papers": sum(len(t.get("papers") or []) for t in topics),
            "n_refs": sum(len(t.get("refs") or []) for t in topics),
            "n_news": sum(len(t.get("news") or []) for t in topics)}


def _picture_fit(slide, name: str, left, top, box_w, box_h,
                 crop_bottom: float = 0.0):
    """按比例把素材放入指定区域（不拉伸），返回是否为 None 表示素材缺失。"""
    path = ASSETS / name
    if not path.exists():
        return None
    pic = slide.shapes.add_picture(str(path), left, top, width=box_w)
    if crop_bottom:
        pic.crop_bottom = crop_bottom
    # 裁剪后可见高度变短，按可见高度的比例重新计算
    vis_h_ratio = 1.0 - crop_bottom
    eff_h = Emu(int(pic.height * vis_h_ratio))
    if eff_h > box_h:
        pic._element.getparent().remove(pic._element)
        pic = slide.shapes.add_picture(str(path), left, top, height=box_h)
        if crop_bottom:
            pic.crop_bottom = crop_bottom
        eff_h = box_h
    # 居中
    pic.left = int(left + (box_w - pic.width) / 2)
    return pic


# ── 各页 ──────────────────────────────────────────────────
def _slide_cover(prs, payload, agg, flt_desc: str = ""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _rect(s, 0, 0, Inches(0.16), SLIDE_H, C_GREEN)
    _rect(s, Inches(0.9), Inches(5.35), Inches(1.4), Inches(0.05), C_GREEN)
    _text(s, Inches(0.9), Inches(1.55), Inches(11.2), Inches(0.4),
          "NSCLC · MOLECULAR INTELLIGENCE BRIEFING", 13, True, C_GREEN)
    _text(s, Inches(0.9), Inches(2.02), Inches(11.5), Inches(0.85),
          "肺癌 EGFR/MET 靶向治疗", 40, True, C_WHITE)
    _text(s, Inches(0.9), Inches(2.92), Inches(11.5), Inches(0.85),
          "科研情报与会议速递", 40, True, C_WHITE)
    _text(s, Inches(0.9), Inches(4.12), Inches(11.2), Inches(0.6),
          "证据体系：PubTator 3 · ClinicalTrials.gov · Open Targets　|　新闻补充：Tavily",
          14, False, C_MUTED)
    if flt_desc:
        _text(s, Inches(0.9), Inches(4.78), Inches(11.2), Inches(0.4),
              "筛选导出 · " + _clean(flt_desc, 76), 12, True, C_AMBER)
    _picture_fit(s, "FigureLogo.png", SLIDE_W - Inches(1.45), Inches(0.72),
                 Inches(0.82), Inches(0.82))
    _text(s, Inches(0.9), Inches(5.62), Inches(11.2), Inches(0.9),
          f"数据截止 {payload.get('latest_generated_at') or TODAY}　"
          f"主题 {agg['n_topics']} 个　证据条目 {agg['n_trials'] + agg['n_papers']} 条　"
          f"来源索引 {agg['n_refs']} 条", 13, False, C_MUTED)
    _footer(s, "AI 生成内容仅供学术参考；全部结论附来源编号，请以原始文献/注册信息为准。")


def _slide_overview(prs, payload, agg, page, flt_desc: str = "",
                    exclude_conf: bool = False):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _header(s, "Overview", "数据总览", page=page)
    cards = [
        (str(agg["n_topics"]), "覆盖主题", C_GREEN),
        (f"{agg['n_recruiting']}/{agg['n_trials']}", "试验（招募中/合计）", C_BLUE),
        (str(agg["n_papers"]), "文献（PMID）", C_AMBER),
        (str(agg["n_refs"]), "来源索引", RGBColor(0x9B, 0x8C, 0xE8)),
        (str(agg["n_news"]), "会议/新闻补充", RGBColor(0x4F, 0xC3, 0xD6)),
    ]
    cw, gap = Inches(2.28), Inches(0.14)
    for i, (v, lab, col) in enumerate(cards):
        _kpi_card(s, MARGIN + i * (cw + gap), Inches(1.72), cw, Inches(1.28), v, lab, col)

    if flt_desc:
        _text(s, MARGIN, Inches(3.10), CONTENT_W, Inches(0.3),
              "筛选条件： " + _clean(flt_desc, 96), 10.5, False, C_AMBER)

    if flt_desc:
        # 筛选态：逐主题列出命中条目（确定性内容，保证随筛选变化）
        _text(s, MARGIN, Inches(3.40), CONTENT_W, Inches(0.3),
              "筛选命中内容（按主题）", 13, True, C_GREEN)
        lines = []
        for t in (payload.get("topics") or []):
            nt = len(t.get("trials") or [])
            np_ = len(t.get("papers") or [])
            nn = len(t.get("news") or [])
            nk = len(t.get("key_trials") or [])
            if not (nt or np_ or nn or nk):
                continue
            lines.append(_clean(f'{t.get("title")}：试验 {nt} 条 · 文献 {np_} 篇 · '
                                f'新闻 {nn} 条 · 会议关键试验 {nk} 行', 120))
            for tr in (t.get("trials") or [])[:2]:
                lines.append(_clean(f'　· {tr.get("nct") or ""} {tr.get("title")}', 104))
            for pp in (t.get("papers") or [])[:2]:
                lines.append(_clean(f'　· PMID {pp.get("pmid")} {pp.get("title")}', 104))
        if lines:
            _bullets(s, MARGIN, Inches(3.74), CONTENT_W, Inches(2.75), lines, 11.5)
        else:
            _text(s, MARGIN, Inches(3.82), CONTENT_W, Inches(0.8),
                  "当前筛选未命中任何条目——请放宽条件后重新导出。", 13, False, C_MUTED)
    else:
        g = payload.get("global") or {}
        items = _synth_bullets(g.get("synth") or "", limit=5, each=132)
        if exclude_conf:
            _CONF_KW = ("ESMO", "WCLC", "ASCO", "AACR", "会议", "congress")
            items = [x for x in items
                     if not any(k.lower() in x.lower() for k in _CONF_KW)] or items
        _text(s, MARGIN, Inches(3.28), CONTENT_W, Inches(0.3),
              "AI 跨主题总结", 13, True, C_GREEN)
        if items:
            _bullets(s, MARGIN, Inches(3.62), CONTENT_W, Inches(2.9), items, 14)
        else:
            _text(s, MARGIN, Inches(3.7), CONTENT_W, Inches(1.0),
                  "（本次未生成跨主题总结，可用 --synth 构建）", 13, False, C_MUTED)
    _footer(s, "来源：PubTator 3 / ClinicalTrials.gov / Open Targets；Tavily 仅作新闻补充 · "
               "编号 [n] 对应各主题来源索引。")


def _slide_method(prs, payload, agg, page):
    """情报体系与方法页：数据源、溯源规则、自动化与免责声明。"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _header(s, "Method", "情报体系与证据链", page=page)
    items = [
        "证据层：PubTator 3（文献+实体标注）、ClinicalTrials.gov（注册试验）、"
        "Open Targets（靶点-疾病-药物，含临床阶段）；",
        "补充层：Tavily 会议/新闻检索，仅作背景，不计入证据强度；",
        "溯源规则：每条证据分配 [n] 编号并可点击跳转原文；AI 结论强制内联引用，"
        "越界编号自动剔除；",
        "会议数据：从公开会议报道逐篇抽取 HR/95%CI/样本量，缺失写「—」，不推断；",
        "自动化：每日 08:00 重建归档；看板实时层另行拉取 ClinicalTrials.gov。",
    ]
    _bullets(s, MARGIN, Inches(1.66), Inches(6.7), Inches(4.9), items, 13)
    _picture_fit(s, "FigureHero.jpg", Inches(7.5), Inches(1.72),
                 Inches(5.25), Inches(3.0), crop_bottom=0.17)
    _text(s, Inches(7.5), Inches(4.92), Inches(5.25), Inches(1.5),
          "分子诊断 → 靶向治疗 → 临床证据：看板按此链条组织四类主题，"
          "并提供可回溯的来源索引。", 11, False, C_MUTED)
    _footer(s, "数据来源与许可：PubTator 3 / ClinicalTrials.gov（公共数据）；"
               "Open Targets（CC BY 4.0）；Tavily（商业检索服务）。")


def _slide_charts(prs, agg, page):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _header(s, "Evidence metrics", "情报结构分析", page=page)
    if agg["status"]:
        _chart(s, XL_CHART_TYPE.DOUGHNUT, MARGIN, Inches(1.75),
               Inches(6.0), Inches(2.55),
               [k for k, _ in agg["status"]], [v for _, v in agg["status"]],
               "试验状态分布", colors=PALETTE)
    if agg["phases"]:
        _chart(s, XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(6.85), Inches(1.75),
               Inches(5.85), Inches(2.55),
               [k for k, _ in agg["phases"]], [v for _, v in agg["phases"]],
               "试验分期分布", legend=False)
    if agg["years"]:
        _chart(s, XL_CHART_TYPE.COLUMN_CLUSTERED, MARGIN, Inches(4.45),
               Inches(6.0), Inches(2.35),
               [k for k, _ in agg["years"]], [v for _, v in agg["years"]],
               "文献年度分布", legend=False)
    if agg["sources"]:
        _chart(s, XL_CHART_TYPE.PIE, Inches(6.85), Inches(4.45),
               Inches(5.85), Inches(2.35),
               [k for k, _ in agg["sources"]], [v for _, v in agg["sources"]],
               "数据源构成", colors=PALETTE)
    _footer(s, "图表为 PowerPoint 原生图表，可直接右键「编辑数据」调整；"
               "计数基于当前归档与实时试验层。")


def _slide_key_trials(prs, topic, page, max_rows=13):
    rows = topic.get("key_trials") or []
    if not rows:
        return False
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _header(s, "Congress data", "ESMO 2026 · 关键注册试验结果（全瘤种）", page=page)
    heads = ["终点", "方案", "试验", "瘤种/场景", "HR", "95%CI", "N", "判定"]
    widths = [Inches(1.28), Inches(2.45), Inches(1.75), Inches(2.55),
              Inches(0.72), Inches(1.15), Inches(0.62), Inches(1.35)]
    body = rows[:max_rows]
    tbl_h = Inches(0.34) * (len(body) + 1)
    shape = s.shapes.add_table(len(body) + 1, len(heads), MARGIN, Inches(1.66),
                               sum(widths, Emu(0)), tbl_h)
    tbl = shape.table
    for i, w in enumerate(widths):
        tbl.columns[i].width = w
    for c, h in enumerate(heads):
        cell = tbl.cell(0, c)
        cell.text = ""
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(0x1B, 0x3A, 0x55)
        p = cell.text_frame.paragraphs[0]
        r = p.add_run()
        r.text = h
        _font(r, 9.5, True, C_WHITE)
    for ri, row in enumerate(body, start=1):
        ci = (f'{row["ci_low"]:g}–{row["ci_high"]:g}'
              if row.get("ci_low") is not None and row.get("ci_high") is not None else "—")
        vals = [_clean(row.get("endpoint"), 8), _clean(row.get("regimen"), 22),
                _clean(row.get("trial"), 16), _clean(row.get("tumor"), 24),
                (f'{row["hr"]:g}' if row.get("hr") is not None else "—"),
                ci, (str(row.get("n")) if row.get("n") is not None else "—"),
                _clean(row.get("verdict"), 10)]
        for c, v in enumerate(vals):
            cell = tbl.cell(ri, c)
            cell.text = ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = C_NAVY2 if ri % 2 else RGBColor(0x10, 0x27, 0x3D)
            cell.margin_left = cell.margin_right = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            r = p.add_run()
            r.text = v
            pos = (row.get("verdict") or "").startswith("达到")
            _font(r, 8.5, c == 7 and pos, C_GREEN if (c == 7 and pos) else C_WHITE)
    _footer(s, f"共 {len(rows)} 行，本页展示前 {len(body)} 行 · AI 从 ESMO 会议报道抽取，"
               "数字请以原文为准 · 每行对应来源索引编号 · 会议数据无日期字段，不随时间筛选变化。")


def _slide_topic(prs, topic, page, filtered: bool = False):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _header(s, "Topic", _clean(topic.get("title"), 34), page=page)

    L_W = Inches(6.15)
    R_X = MARGIN + Inches(6.55)
    R_W = CONTENT_W - Inches(6.55)

    # ── 左栏：AI 解读 ──
    if filtered:
        _text(s, MARGIN, Inches(1.60), L_W, Inches(0.28),
              "筛选命中条目（按当前条件）", 11.5, True, C_GREEN)
        fb = []
        for tr in (topic.get("trials") or [])[:2]:
            fb.append(_clean(f'{tr.get("nct") or ""} · {tr.get("title")}'
                             f'（{tr.get("status_cn") or tr.get("status") or ""}）', 100))
        for pp in (topic.get("papers") or [])[:2]:
            fb.append(_clean(f'PMID {pp.get("pmid")} · {pp.get("title")}', 100))
        for nn in (topic.get("news") or [])[:1]:
            fb.append(_clean(f'会议/新闻 · {nn.get("title")}', 100))
        bullets = fb or ["（该主题在当前筛选下无命中条目）"]
    else:
        _text(s, MARGIN, Inches(1.60), L_W, Inches(0.28),
              "AI 关键解读（带来源编号）", 11.5, True, C_GREEN)
        bullets = _synth_bullets(topic.get("synth") or "", limit=4, each=104)
    if bullets:
        _bullets(s, MARGIN, Inches(1.92), L_W, Inches(2.75), bullets, 12)
    else:
        _text(s, MARGIN, Inches(1.96), L_W, Inches(0.6), "（本次未生成解读）",
              11.5, False, C_MUTED)

    # ── 左栏下部：关键文献 ──
    papers = (topic.get("papers") or [])[:2]
    _text(s, MARGIN, Inches(4.86), L_W, Inches(0.28),
          "关键文献（PMID）", 11.5, True, C_AMBER)
    if papers:
        pitems = [_clean(f'PMID {p.get("pmid")} · {p.get("title")}'
                         f'（{p.get("year") or "年份未注明"}）', 96) for p in papers]
        _bullets(s, MARGIN, Inches(5.18), L_W, Inches(1.55), pitems, 10.5,
                 bullet_color=C_AMBER)
    else:
        _text(s, MARGIN, Inches(5.22), L_W, Inches(0.5), "（暂无文献）", 10.5,
              False, C_MUTED)

    # ── 右栏：机制图 + 在研试验 ──
    fig = TOPIC_FIG.get(topic.get("id"))
    fig_h = Inches(2.05)
    if fig:
        _picture_fit(s, fig, R_X, Inches(1.60), R_W, fig_h, crop_bottom=0.09)
    trials = [t for t in (topic.get("trials") or [])
              if t.get("status") in ("RECRUITING", "ACTIVE_NOT_RECRUITING",
                                     "ENROLLING_BY_INVITATION")][:3]
    ty = Inches(3.78)
    _text(s, R_X, ty, R_W, Inches(0.28),
          f"在研试验（{len(trials)}）", 11.5, True, C_BLUE)
    if trials:
        items = []
        for t in trials:
            ph = "/".join(t.get("phase") or [])
            items.append(_clean(f'{t.get("nct") or ""} · {t.get("title")}'
                                f'{("（" + ph + "）") if ph else ""}', 62))
        _bullets(s, R_X, ty + Inches(0.30), R_W, Inches(1.9), items, 10,
                 bullet_color=C_BLUE)
    else:
        _text(s, R_X, ty + Inches(0.32), R_W, Inches(0.6),
              "（本主题不采集试验列表）", 10, False, C_MUTED)

    _footer(s, f"证据 {len(topic.get('trials') or []) + len(topic.get('papers') or [])} 条 · "
               f"来源索引 {len(topic.get('refs') or [])} 条 · 编号 [n] 可回溯原文 · AI 内容仅供参考。")


def _slide_sources(prs, topics, page, max_rows=26):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _header(s, "Appendix", "来源索引（节选）", page=page)
    lines = []
    for t in topics:
        tid = t.get("id")
        for src in (t.get("refs") or [])[:6]:
            lines.append(_clean(f'[{src.get("n")}] {src.get("kind")} · '
                                f'{(src.get("label") or "")[:96]}', 118))
            if len(lines) >= max_rows:
                break
        if len(lines) >= max_rows:
            break
    _bullets(s, MARGIN, Inches(1.66), CONTENT_W, Inches(5.2), lines, 10.5,
             bullet_color=C_MUTED)
    _footer(s, "完整来源索引见互动看板各主题页（可点击跳转原文）。")


def _slide_closing(prs, agg):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, C_NAVY)
    _rect(s, 0, 0, Inches(0.16), SLIDE_H, C_GREEN)
    _text(s, Inches(0.9), Inches(2.3), Inches(11.4), Inches(0.9),
          "小结", 40, True, C_WHITE)
    pts = [
        f"本轮共汇集 {agg['n_topics']} 个主题、{agg['n_trials']} 项试验、"
        f"{agg['n_papers']} 篇文献与 {agg['n_refs']} 条来源索引；",
        "全部结论附编号引用，可逐条回溯到 PMID / NCT / 靶点页面；",
        "会议数据由 AI 从公开报道抽取，正式引用前请核对原始摘要；",
        "数据每日 08:00 自动更新，互动看板支持筛选与检索。",
    ]
    _bullets(s, Inches(0.9), Inches(3.4), Inches(11.2), Inches(2.6), pts, 15)
    _text(s, Inches(0.9), Inches(6.2), Inches(11.2), Inches(0.4),
          f"AImednews · 生成于 {TODAY} · 来源：PubTator 3 / ClinicalTrials.gov / "
          "Open Targets / Tavily", 11, False, C_MUTED)


# ── 入口 ──────────────────────────────────────────────────
def build_pptx(payload: Dict[str, Any], flt_desc: str = "",
               exclude_conf: bool = False) -> bytes:
    agg = _agg(payload)
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H

    _slide_cover(prs, payload, agg, flt_desc)
    page = 2
    _slide_overview(prs, payload, agg, page, flt_desc, exclude_conf); page += 1
    _slide_method(prs, payload, agg, page); page += 1
    _slide_charts(prs, agg, page); page += 1

    for t in (payload.get("topics") or []):
        rows = t.get("key_trials") or []
        if flt_desc and not (rows or t.get("trials") or t.get("papers")
                             or t.get("news") or t.get("targets")):
            continue
        if rows:
            # 会议主题：先关键试验表（可能多页），再解读页
            chunks = [rows[i:i + 13] for i in range(0, min(len(rows), 39), 13)]
            for ch in chunks:
                sub = dict(t); sub["key_trials"] = ch
                _slide_key_trials(prs, sub, page); page += 1
        _slide_topic(prs, t, page, filtered=bool(flt_desc)); page += 1

    _slide_sources(prs, payload.get("topics") or [], page); page += 1
    _slide_closing(prs, agg)

    bio = io.BytesIO()
    prs.save(bio)
    return bio.getvalue()