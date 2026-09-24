#!/usr/bin/env python3

import argparse
from html import escape
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from aigc_rules import find_placeholders
from ai_compliance import generate as generate_ai_compliance
from output_names import (manual_html_name, manual_pdf_name,
                          source_material_html_name, source_material_pdf_name,
                          submission_dir, manual_page_window)
from source_material_render import write_source_html_from_config

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
            return f'<h1 id="chapter-{i}" class="chapter-heading">{i:02d}-{chapter}</h1>'
        return f'<h1 id="chapter-{i}">{chapter}</h1>'
    return re.sub(r"<h1[^>]*>(.*?)</h1>", repl, html, flags=re.S)


def group_screenshot_figures(html):
    """Keep a screenshot and its following Markdown caption together.

    Pandoc emits an image and an explicit caption as two adjacent paragraphs:
    ``<p><img ...></p><p>图 7-1 ...</p>``.  Chromium is then free to put the
    image at the bottom of one page and the caption at the top of the next.
    Wrap both (and image-only paragraphs) in a ``figure`` so the CSS
    ``page-break-inside: avoid`` rule applies to the complete evidence block.
    """
    captioned = re.compile(
        r'<p>(<img\b[^>]*>)</p>\s*<p>(图\s*[0-9０-９]+(?:\s*[-－—]\s*[0-9０-９]+)?[^<]*)</p>',
        flags=re.S,
    )
    html = captioned.sub(
        r'<figure class="screenshot-figure">\1<figcaption>\2</figcaption></figure>',
        html,
    )
    image_only = re.compile(r'<p>(<img\b[^>]*>)</p>', flags=re.S)
    return image_only.sub(r'<figure class="screenshot-figure">\1</figure>', html)


def html_doc(title, body, version="", style="reference", chapters=None):
    if style not in STYLE_CHOICES:
        raise ValueError(f"未知说明书样式 {style!r}，可选：{', '.join(STYLE_CHOICES)}")
    chapters = chapters or list(CHAPTERS)
    if style == "reference":
        links = "\n".join(f'<li><a href="#chapter-{i+1}">{i+1:02d}-{c}</a></li>' for i, c in enumerate(chapters))
        page_css = """@page { size: A4; margin: 20mm 19mm 17mm;
  @top-left { content: \"\"; }
  @bottom-right { content: counter(page); font-size: 10pt; color: #555; }
}
@page :first { @top-left { content: \"\"; } @bottom-right { content: counter(page); } }"""
        cover_css = """.cover { min-height:225mm; page-break-after:always; }
.cover h1 { font-size:34px; margin:0 0 10mm; padding-bottom:4mm; border-bottom:1px solid #d1d5db; }
.cover .doc-kind { font-size:22px; color:#555; margin:-5mm 0 10mm; }
.cover ul { list-style:none; margin:0; padding:0; font-size:18px; line-height:1.55; }
.cover li { margin:0; padding:1.9mm 0; }
.cover li a { display:block; color:#1677ff; }"""
        heading_css = """h1 { page-break-before:always; page-break-after:avoid; break-after:avoid; font-size:30px; margin:0 0 5mm; padding-bottom:4mm; border-bottom:1px solid #d1d5db; color:#262626; }
h1:first-child { page-break-before:auto; }
h2 { font-size:22px; margin:7mm 0 3mm; page-break-after:avoid; break-after:avoid; }
h3 { font-size:18px; margin:5mm 0 2mm; }"""
        body_css = """body { font-family: -apple-system,BlinkMacSystemFont,\"PingFang SC\",\"Microsoft YaHei\",Arial,sans-serif; font-size:16px; line-height:2.0; color:#262626; }
p { margin:0 0 4mm; text-align:justify; }
li { margin:0 0 2mm; }
table { width:100%; border-collapse:collapse; margin:5mm 0 7mm; font-size:14px; line-height:1.65; page-break-inside:avoid; }
th,td { border:1px solid #d1d5db; padding:6px 8px; vertical-align:top; }
th { background:#f7f7f7; }"""
    else:
        links = "\n".join(f'<li><a href="#chapter-{i+1}">{i+1}. {c}</a></li>' for i, c in enumerate(chapters))
        page_css = """@page { size: A4; margin: 22mm 19mm 18mm;
  @top-left { content: \"\"; }
  @bottom-center { content: counter(page); font-size: 9pt; color: #6b7280; }
}
@page :first { @top-left { content: \"\"; } @bottom-center { content: \"\"; } }"""
        cover_css = """.cover { min-height:225mm; page-break-after:always; }
.cover h1 { font-size:32px; margin:0 0 18mm; padding-bottom:4mm; border-bottom:2px solid #111827; }
.cover .doc-kind { font-size:21px; color:#4b5563; margin:-10mm 0 16mm; }
.cover ul { list-style:none; margin:0 14mm; padding:0; font-size:20px; line-height:1.55; }
.cover li { margin:0; padding:4.2mm 0; border-bottom:1px solid #e5e7eb; }
.cover li a { display:block; color:#111827; }"""
        heading_css = """h1 { page-break-before:always; page-break-after:avoid; break-after:avoid; font-size:28px; margin:0 0 8mm; padding-bottom:4mm; border-bottom:2px solid #111827; }
h1:first-child { page-break-before:auto; }
h2 { font-size:20px; margin:8mm 0 4mm; page-break-after:avoid; break-after:avoid; }
h3 { font-size:17px; margin:6mm 0 3mm; }"""
        body_css = """body { font-family: -apple-system,BlinkMacSystemFont,\"PingFang SC\",\"Microsoft YaHei\",Arial,sans-serif; font-size:16px; line-height:2.12; color:#111827; }
p { margin:0 0 4.8mm; text-align:justify; }
li { margin:0 0 2.4mm; }
table { width:100%; border-collapse:collapse; margin:6mm 0 8mm; font-size:14px; line-height:1.68; page-break-inside:avoid; }
th,td { border:1px solid #c9ced6; padding:7px 9px; vertical-align:top; }
th { background:#f3f4f6; }"""
    body = group_screenshot_figures(anchor_h1(body, title, style))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
{page_css}
{cover_css}
a {{ color:#111827; text-decoration:none; }}
{heading_css}
{body_css}
/* Screenshots are submission evidence, not decorative thumbnails.  Keep the
   full-width image visible in the printed page while preserving its aspect
   ratio; Chromium embeds the local PNG/JPEG bytes in the PDF. */
figure.screenshot-figure {{ margin: 4mm auto 7mm; text-align: center; break-inside: avoid; page-break-inside: avoid; -webkit-column-break-inside: avoid; }}
figure.screenshot-figure img {{ max-width: 100%; max-height: 145mm; width: auto; height: auto; display: block; margin: 0 auto 2mm; border: 1px solid #d0d7de; }}
figure.screenshot-figure figcaption {{ font-size: 14px; line-height: 1.5; color: #4b5563; text-align: center; }}
pre {{ white-space:pre-wrap; word-break:break-word; font-size:12.5px; line-height:1.65; background:#f6f8fa; padding:12px 14px; border:1px solid #d0d7de; }}
</style></head><body><section class="cover"><h1>{title}</h1><div class="doc-kind">软件说明书</div><ul>{links}</ul></section><main>{body}</main></body></html>"""


class PlaceholderError(RuntimeError):
    """说明书仍含草稿占位符，不能生成提交件。"""


def placeholder_gate(md_path, md):
    hits = find_placeholders(md)
    if hits:
        lines = "\n".join(f"  {md_path}:{no}  {text}" for no, text in hits[:50])
        more = f"\n  ……另有 {len(hits) - 50} 处" if len(hits) > 50 else ""
        raise PlaceholderError(
            f"说明书仍有 {len(hits)} 处草稿占位符，拒绝生成提交用 PDF：\n{lines}{more}\n"
            "处理：补真实内容/真实截图，或删除该句/该图位；不得用编造内容替换。")


def render_software_pdf(root, project, style, config=None):
    d = root / project["id"]
    md_path = d / "软件说明书.md"
    if not md_path.exists():
        raise PlaceholderError(f"缺少 {md_path}，请先运行 generate_docs.py 生成说明书。")
    md = md_path.read_text(encoding="utf-8")
    final_dir = submission_dir(d)
    final_dir.mkdir(parents=True, exist_ok=True)
    pdf = final_dir / manual_pdf_name(project)
    try:
        placeholder_gate(md_path, md)
    except PlaceholderError:
        # 旧的提交件同样不可信，移到草稿名，避免被上传清单或浏览器误选
        if pdf.exists():
            pdf.replace(pdf.with_name(pdf.stem + "-含占位符作废.pdf"))
        raise
    chapters = chapter_titles(md)
    body = md_to_html(strip_toc(md))
    html = d / manual_html_name(project)
    html.write_text(html_doc(project["name"], body, project.get("version", "V1.0"), style, chapters), encoding="utf-8")
    run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.resolve().as_uri()])
    actual_pages = pages(pdf)
    low, high, target = manual_page_window(project, config)
    if actual_pages is not None and not low <= actual_pages <= high:
        print(
            f"[{project['name']}] 说明书 {actual_pages} 页，偏离约 {target} 页目标（建议 {low}–{high} 页）；"
            "请只补充或删减真实内容，不要用空白页或重复段落凑页数。",
            file=sys.stderr,
        )
    print(f"{pdf} => {actual_pages} pages")


def render_source_pdf(root, project, config, repo=None):
    """直接将裁剪后的源码 HTML 打印为 PDF，不依赖 LibreOffice/WPS/Word。"""
    d = root / project["id"]
    source_dir = d / "源程序提取"
    source_dir.mkdir(parents=True, exist_ok=True)
    html = source_dir / source_material_html_name(project)
    if not html.exists():
        if repo is None:
            raise RuntimeError(
                f"缺少源程序 HTML：{html}。请先运行 generate_source_docx.py，"
                "或给 render_pdfs.py 传 --repo 以直接构建 Chromium 输入。"
            )
        collected = write_source_html_from_config(repo, config, project, html)
        if collected["skipped"]:
            print(f"[{project['name']}] 跳过 {len(collected['skipped'])} 个第三方文件："
                  + "、".join(r for r, _ in collected["skipped"]), file=sys.stderr)
        if collected["missing"]:
            print(f"[{project['name']}] 缺失 {len(collected['missing'])} 个源码文件："
                  + "、".join(collected["missing"]), file=sys.stderr)
        need = collected["pages"] * collected["lines_per_page"]
        if len(collected["lines"]) < need:
            print(f"[{project['name']}] 警告：可用代码 {len(collected['lines'])} 行，不足 {need} 行",
                  file=sys.stderr)
    final_dir = submission_dir(d)
    final_dir.mkdir(parents=True, exist_ok=True)
    pdf = final_dir / source_material_pdf_name(project)
    run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", html.resolve().as_uri()])
    print(f"{pdf} => {pages(pdf)} pages")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    parser.add_argument("--style", choices=STYLE_CHOICES, default=None,
                        help="说明书样式；默认读取配置，未配置时使用 reference")
    parser.add_argument("--repo", help="源码仓库路径；缺少源程序 HTML 时用于直接构建 Chromium 输入")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    repo = Path(args.repo).resolve() if args.repo else None
    failed = []
    for project in cfg["projects"]:
        style = args.style or project.get("document_style") or cfg.get("document_style", "reference")
        if style not in STYLE_CHOICES:
            raise SystemExit(f"document_style 必须是 {', '.join(STYLE_CHOICES)} 之一，当前为 {style!r}")
        try:
            render_software_pdf(root, project, style, cfg)
        except PlaceholderError as exc:
            failed.append(project["id"])
            print(f"[{project['name']}] {exc}", file=sys.stderr)
        render_source_pdf(root, project, cfg, repo)
        declaration = generate_ai_compliance(root, cfg, project, pdf=True)
        if declaration["enabled"]:
            print(f"AI 合规声明：{declaration['directory']}（需核对并签署）")
    if failed:
        raise SystemExit(f"说明书 PDF 未生成：{'、'.join(failed)}")


if __name__ == "__main__":
    main()
