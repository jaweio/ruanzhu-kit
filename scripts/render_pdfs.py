#!/usr/bin/env python3

import argparse
from html import escape
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

CHAPTERS = ["软件概述", "软件架构", "环境要求", "安装部署", "配置说明", "使用指南", "功能模块", "运维管理", "常见问题", "附录"]
STYLE_CHOICES = ("reference", "clean")


def _find_tool(env, hardcoded, candidates):
    for p in [os.environ.get(env), hardcoded, *candidates]:
        if p and Path(p).exists():
            return p
    return shutil.which(Path(hardcoded).name)


CHROME = _find_tool("RUANZHU_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    ["/Applications/Chromium.app/Contents/MacOS/Chromium"])
PDFINFO = _find_tool("RUANZHU_PDFINFO",
                     "pdfinfo",
                     ["/opt/homebrew/bin/pdfinfo", "/usr/local/bin/pdfinfo"])
SOFFICE = _find_tool("RUANZHU_SOFFICE",
                     "soffice",
                     ["/opt/homebrew/bin/soffice", "/usr/local/bin/soffice",
                      "/Applications/LibreOffice.app/Contents/MacOS/soffice"])


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs)


def pages(pdf):
    if PDFINFO:
        out = run([PDFINFO, str(pdf)]).stdout
        m = re.search(r"^Pages:\s+(\d+)", out, re.M)
        return int(m.group(1)) if m else None
    # 无 pdfinfo 时用 PDF 对象粗算页数（对 Chrome/LibreOffice 输出基本可靠）
    data = Path(pdf).read_bytes()
    counts = re.findall(rb"/Type\s*/Page[^s]", data)
    if counts:
        return len(counts)
    m = re.search(rb"/Count\s+(\d+)", data)
    return int(m.group(1)) if m else None


def md_to_html(md):
    return run(["pandoc", "--from", "gfm", "--to", "html"], input=md).stdout


def strip_toc(md):
    idx = md.find("\n# 软件概述")
    return md[idx + 1 :] if idx >= 0 else md


def chapter_titles(md):
    """从实际 Markdown 标题读取章节，支持默认十章之外的扩展章节。"""
    titles = []
    for line in strip_toc(md).splitlines():
        if not line.startswith("# ") or line.startswith("## "):
            continue
        title = re.sub(r"^#\s+", "", line).strip()
        title = re.sub(r"^\d+\s+", "", title)
        if title:
            titles.append(title)
    return titles or list(CHAPTERS)


def anchor_h1(html, title, style):
    i = 0
    def repl(m):
        nonlocal i
        i += 1
        chapter = re.sub(r"^\s*\d+\s+", "", m.group(1).strip())
        if style == "reference":
            return (f'<h1 id="chapter-{i}" class="chapter-heading">{i:02d}-{chapter}</h1>'
                    f'<div class="chapter-title">{escape(title)} - {chapter}</div>')
        return f'<h1 id="chapter-{i}">{chapter}</h1>'
    return re.sub(r"<h1[^>]*>(.*?)</h1>", repl, html, flags=re.S)


def html_doc(title, body, version="", style="reference", chapters=None):
    if style not in STYLE_CHOICES:
        raise ValueError(f"未知说明书样式 {style!r}，可选：{', '.join(STYLE_CHOICES)}")
    chapters = chapters or list(CHAPTERS)
    if style == "reference":
        links = "\n".join(f'<li><a href="#chapter-{i+1}">{i+1:02d}-{c}</a></li>' for i, c in enumerate(chapters))
        page_css = """@page { size: Letter; margin: 20mm 19mm 17mm;
  @top-left { content: \"\"; }
  @bottom-right { content: counter(page); font-size: 10pt; color: #555; }
}
@page :first { @top-left { content: \"\"; } @bottom-right { content: counter(page); } }"""
        cover_css = """.cover { min-height:225mm; page-break-after:always; }
.cover h1 { font-size:34px; margin:0 0 10mm; padding-bottom:4mm; border-bottom:1px solid #d1d5db; }
.cover ul { list-style:none; margin:0; padding:0; font-size:18px; line-height:1.55; }
.cover li { margin:0; padding:1.9mm 0; }
.cover li a { display:block; color:#1677ff; }"""
        heading_css = """h1 { page-break-before:always; font-size:30px; margin:0 0 5mm; padding-bottom:4mm; border-bottom:1px solid #d1d5db; color:#262626; }
h1:first-child { page-break-before:auto; }
.chapter-title { font-size:28px; line-height:1.35; font-weight:700; margin:0 0 7mm; color:#262626; }
h2 { font-size:22px; margin:7mm 0 3mm; }
h3 { font-size:18px; margin:5mm 0 2mm; }"""
        body_css = """body { font-family: -apple-system,BlinkMacSystemFont,\"PingFang SC\",\"Microsoft YaHei\",Arial,sans-serif; font-size:16px; line-height:2.0; color:#262626; }
p { margin:0 0 4mm; text-align:justify; }
li { margin:0 0 2mm; }
table { width:100%; border-collapse:collapse; margin:5mm 0 7mm; font-size:14px; line-height:1.65; page-break-inside:avoid; }
th,td { border:1px solid #d1d5db; padding:6px 8px; vertical-align:top; }
th { background:#f7f7f7; }"""
    else:
        links = "\n".join(f'<li><a href="#chapter-{i+1}">{i+1}. {c}</a></li>' for i, c in enumerate(chapters))
        page_css = """@page { size: Letter; margin: 22mm 19mm 18mm;
  @top-left { content: \"\"; }
  @bottom-center { content: counter(page); font-size: 9pt; color: #6b7280; }
}
@page :first { @top-left { content: \"\"; } @bottom-center { content: \"\"; } }"""
        cover_css = """.cover { min-height:225mm; page-break-after:always; }
.cover h1 { font-size:32px; margin:0 0 18mm; padding-bottom:4mm; border-bottom:2px solid #111827; }
.cover ul { list-style:none; margin:0 14mm; padding:0; font-size:20px; line-height:1.55; }
.cover li { margin:0; padding:4.2mm 0; border-bottom:1px solid #e5e7eb; }
.cover li a { display:block; color:#111827; }"""
        heading_css = """h1 { page-break-before:always; font-size:28px; margin:0 0 8mm; padding-bottom:4mm; border-bottom:2px solid #111827; }
h1:first-child { page-break-before:auto; }
h2 { font-size:20px; margin:8mm 0 4mm; }
h3 { font-size:17px; margin:6mm 0 3mm; }"""
        body_css = """body { font-family: -apple-system,BlinkMacSystemFont,\"PingFang SC\",\"Microsoft YaHei\",Arial,sans-serif; font-size:16px; line-height:2.12; color:#111827; }
p { margin:0 0 4.8mm; text-align:justify; }
li { margin:0 0 2.4mm; }
table { width:100%; border-collapse:collapse; margin:6mm 0 8mm; font-size:14px; line-height:1.68; page-break-inside:avoid; }
th,td { border:1px solid #c9ced6; padding:7px 9px; vertical-align:top; }
th { background:#f3f4f6; }"""
    body = anchor_h1(body, title, style)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
{page_css}
{cover_css}
a {{ color:#111827; text-decoration:none; }}
{heading_css}
{body_css}
img {{ max-width: 85%; max-height: 105mm; display: block; margin: 4mm auto 2mm; border: 1px solid #d0d7de; page-break-inside: avoid; }}
pre {{ white-space:pre-wrap; word-break:break-word; font-size:12.5px; line-height:1.65; background:#f6f8fa; padding:12px 14px; border:1px solid #d0d7de; }}
</style></head><body><section class="cover"><h1>{title}</h1><ul>{links}</ul></section><main>{body}</main></body></html>"""


def render_software_pdf(root, project, style):
    d = root / project["id"]
    md = (d / "软件说明书.md").read_text(encoding="utf-8")
    chapters = chapter_titles(md)
    body = md_to_html(strip_toc(md))
    html = d / "软件文档.html"
    pdf = d / "软件文档.pdf"
    html.write_text(html_doc(project["name"], body, project.get("version", "V1.0"), style, chapters), encoding="utf-8")
    run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.resolve().as_uri()])
    print(f"{pdf} => {pages(pdf)} pages")


def render_docx_pdfs(root, project):
    d = root / project["id"]
    for docx in list(d.glob("软件说明书.docx")) + list((d / "源程序提取").glob("源程序鉴别材料-*页.docx")):
        run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)])
        pdf = docx.with_suffix(".pdf")
        print(f"{pdf} => {pages(pdf)} pages")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    parser.add_argument("--style", choices=STYLE_CHOICES, default=None,
                        help="说明书样式；默认读取配置，未配置时使用 reference")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    for project in cfg["projects"]:
        style = args.style or project.get("document_style") or cfg.get("document_style", "reference")
        if style not in STYLE_CHOICES:
            raise SystemExit(f"document_style 必须是 {', '.join(STYLE_CHOICES)} 之一，当前为 {style!r}")
        render_software_pdf(root, project, style)
        render_docx_pdfs(root, project)


if __name__ == "__main__":
    main()
