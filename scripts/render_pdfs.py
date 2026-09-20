#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

CHAPTERS = ["软件概述", "软件架构", "环境要求", "安装部署", "配置说明", "使用指南", "功能模块", "运维管理", "常见问题", "附录"]


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


def anchor_h1(html):
    i = 0
    def repl(m):
        nonlocal i
        i += 1
        return f'<h1 id="chapter-{i}">{m.group(1)}</h1>'
    return re.sub(r"<h1[^>]*>(.*?)</h1>", repl, html, flags=re.S)


def html_doc(title, body, version=""):
    links = "\n".join(f'<li><a href="#chapter-{i+1}">{i+1}. {c}</a></li>' for i, c in enumerate(CHAPTERS))
    body = anchor_h1(body)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
@page {{ size: Letter; margin: 22mm 19mm 18mm;
  @top-left {{ content: "{title} {version}"; font-size: 9pt; color: #555; }}
  @bottom-right {{ content: "第 " counter(page) " 页 / 共 " counter(pages) " 页"; font-size: 9pt; color: #555; }}
}}
@page :first {{ @top-left {{ content: ""; }} @bottom-right {{ content: ""; }} }}
body {{ font-family: -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Arial,sans-serif; font-size:16px; line-height:2.12; color:#111827; }}
.cover {{ min-height:244mm; page-break-after:always; }}
.cover h1 {{ font-size:32px; margin:0 0 22mm; }}
.cover ul {{ list-style:none; padding:0; font-size:20px; line-height:2.18; }}
.cover li::before {{ content:"●"; display:inline-block; width:1.4em; }}
a {{ color:#111827; text-decoration:none; }}
h1 {{ page-break-before:always; font-size:28px; margin:0 0 8mm; }}
h1:first-child {{ page-break-before:auto; }}
h1::before {{ content:"● "; }}
h2 {{ font-size:20px; margin:8mm 0 4mm; }}
h3 {{ font-size:17px; margin:6mm 0 3mm; }}
p {{ margin:0 0 4.8mm; text-align:justify; }}
li {{ margin:0 0 2.4mm; }}
table {{ width:100%; border-collapse:collapse; margin:6mm 0 8mm; font-size:14px; line-height:1.68; page-break-inside:avoid; }}
th,td {{ border:1px solid #c9ced6; padding:7px 9px; vertical-align:top; }}
th {{ background:#f3f4f6; }}
img {{ max-width: 85%; max-height: 105mm; display: block; margin: 4mm auto 2mm; border: 1px solid #d0d7de; page-break-inside: avoid; }}
pre {{ white-space:pre-wrap; word-break:break-word; font-size:12.5px; line-height:1.65; background:#f6f8fa; padding:12px 14px; border:1px solid #d0d7de; }}
</style></head><body><section class="cover"><h1>{title}</h1><ul>{links}</ul></section><main>{body}</main></body></html>"""


def render_software_pdf(root, project):
    d = root / project["id"]
    md = (d / "软件说明书.md").read_text(encoding="utf-8")
    body = md_to_html(strip_toc(md))
    html = d / "软件文档.html"
    pdf = d / "软件文档.pdf"
    html.write_text(html_doc(project["name"], body, project.get("version", "V1.0")), encoding="utf-8")
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
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    for project in cfg["projects"]:
        render_software_pdf(root, project)
        render_docx_pdfs(root, project)


if __name__ == "__main__":
    main()

