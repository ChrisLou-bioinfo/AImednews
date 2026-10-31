# 署名与使用要求（NOTICE）

**项目**：肺癌分子诊疗情报看板 (AImednews) — NSCLC Molecular Intelligence Dashboard
**作者**：Chris Lou (GitHub: [ChrisLou-bioinfo](https://github.com/ChrisLou-bioinfo))
**邮箱**：**loujiacheng1986@foxmail.com**
**项目地址**：https://github.com/ChrisLou-bioinfo/AImednews
**许可**：[CC BY-NC 4.0](LICENSE)（署名—非商业性使用 4.0 国际）

---

## 1. 非商业用途

本项目仅授权**非商业性**使用。你可以自由复制、分发、改编与二次开发，但不得将其主要用于
商业目的或获取商业利益。商业使用请另行联系 **loujiacheng1986@foxmail.com** 取得授权。

## 2. 必须署名并标注引用

任何使用、复制、改编、再分发，以及基于本项目的论文、报告、演示、课程材料或软件产品，
**必须显著标注**下列全部信息：

```
项目名称：肺癌分子诊疗情报看板 (AImednews)
作者：Chris Lou (ChrisLou-bioinfo)
邮箱：loujiacheng1986@foxmail.com
项目地址：https://github.com/ChrisLou-bioinfo/AImednews
许可：CC BY-NC 4.0
```

学术发表建议引用格式：

```bibtex
@software{lou2026aimednews,
  author       = {Lou, Chris},
  title        = {AImednews: NSCLC Molecular Intelligence Dashboard},
  year         = {2026},
  howpublished = {\url{https://github.com/ChrisLou-bioinfo/AImednews}},
  note         = {CC BY-NC 4.0. Contact: loujiacheng1986@foxmail.com}
}
```

## 3. 保留标识

分发本项目或其改编版本时，必须完整保留本文件与 `LICENSE`，不得删除或隐藏作者署名、
邮箱地址与项目地址。

## 4. 生成物中的署名

本项目在生成物中内嵌署名，以便随产物传播：

- 看板页面页脚（`webapp/index.html`）
- 导出的 PowerPoint（封面与结尾页，`webapp/ppt_deck.py`）
- 静态看板页脚（`news/config.py` 的 `DASHBOARD["attribution"]`）

移除上述署名视为未满足署名义务。

## 5. 上游数据

本许可仅覆盖本项目自身的源代码、文档与数据组织方式。由 ClinicalTrials.gov、PubMed/PubTator 3、
Open Targets、Tavily 等平台提供的数据，其版权与条款归各平台所有（Open Targets 为 CC BY 4.0，
使用时仍需署名），使用时应同时遵守其各自条款。

---

版权所有 © 2026 Chris Lou · **loujiacheng1986@foxmail.com**
