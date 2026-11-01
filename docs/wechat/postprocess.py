#!/usr/bin/env python3
"""把 wechatctl pack 产出的 content-1.html 调整为可直接进草稿箱的成品。

做三件事：
1) 删除转换器自动插入的"全选复制"提示框（读者在微信里看不到复制场景）；
2) 删除与公众号标题重复的正文 H1；
3) 在指定锚点后注入正文配图（草稿阶段由 wechatctl 自动 uploadimg 换域名）。

用法：python3 docs/wechat/postprocess.py docs/wechat/wechat
"""
import pathlib
import re
import shutil
import sys

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs/wechat/wechat")
html_path = out / "content-1.html"
h = html_path.read_text(encoding="utf-8")

# 1) 去"全选复制"提示框
h = re.sub(r'<div style="background:#e8f7ee;.*?</div>\s*', "", h, count=1, flags=re.S)

# 2) 去正文中与标题重复的 H1（保留第一个 h2 之前的正文）
h = re.sub(r'<h1[^>]*>.*?</h1>\s*', "", h, count=1, flags=re.S)

# 3) 注入配图
def img(name, cap=""):
    caption = (f'<p style="font-size:13px;color:#888;text-align:center;margin:-6px 0 18px;">{cap}</p>'
               if cap else "")
    return (f'<p style="text-align:center;margin:18px 0 6px;">'
            f'<img src="{name}" style="max-width:100%;border-radius:6px;"></p>{caption}')

INSERTS = [
    ("能换配色、能改字号。", "fig2-ppt-overview.png",
     "导出的 PPT：原生图表与版式，可在 PowerPoint 里直接改"),
    ("会议内容默认不导出，需要时勾一下。", "fig3-ppt-topic.png",
     "主题页：AI 解读 + 机制图 + 在研试验 + 关键文献"),
]
for anchor, name, cap in INSERTS:
    if name in h:
        continue
    i = h.find(anchor)
    if i < 0:
        print(f"  ! 未找到锚点：{anchor}")
        continue
    end = h.find("</p>", i) + 4
    h = h[:end] + "\n" + img(name, cap) + h[end:]
    src = pathlib.Path("docs/wechat") / name
    if src.exists():
        shutil.copy(src, out / name)

html_path.write_text(h, encoding="utf-8")
print("  images:", re.findall(r'<img[^>]+src="([^"]+)"', h))
print("  chars:", len(h), "| 提示框残留:", "有" if "全选" in h else "无",
      "| H1 残留:", "有" if "<h1" in h else "无")
