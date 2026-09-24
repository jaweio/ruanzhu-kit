#!/usr/bin/env python3
"""源程序鉴别材料的共享读取与 HTML 打印模板。

DOCX 和 PDF 都必须使用同一份裁剪、脱敏后的代码行，避免两个提交件内容不一致。
PDF 路径不依赖 python-docx 或办公软件，交给 Chromium 负责分页和打印。
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from copyright_check import redact_line
from oss_scrub import own_tokens, scrub_code, third_party_reasons
from source_material import compact_blank_lines, strip_comments, strip_imports


def read_lines(repo, files, redact=True, tokens=(), scrub=True, trim_comments=True,
               trim_imports=True, max_blank_lines=1):
    """读取取材文件：只裁剪输出材料，不改写源文件。

    返回 ``(lines, missing, skipped, stats)``，与历史 generate_source_docx API 兼容。
    """
    lines, missing, skipped = [], [], []
    stats = {"headers": 0, "dropped": 0, "comments": 0, "imports": 0, "blank_lines": 0}
    for rel in files:
        p = repo / rel
        if not p.exists():
            missing.append(rel)
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        reasons = third_party_reasons(rel, text, tokens)
        if reasons:
            skipped.append((rel, "；".join(reasons)))
            continue
        if scrub:
            file_lines, scrub_stats = scrub_code(text, tokens)
            stats["headers"] += scrub_stats["header"]
            stats["dropped"] += scrub_stats["dropped"]
        else:
            file_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if trim_comments:
            file_lines, removed = strip_comments(file_lines, rel)
            stats["comments"] += removed
        if trim_imports:
            file_lines, removed = strip_imports(file_lines, rel)
            stats["imports"] += removed
        before_compact = len(file_lines)
        file_lines = compact_blank_lines(file_lines, max_blank_lines)
        stats["blank_lines"] += max(0, before_compact - len(file_lines))
        for line in file_lines:
            line = line.replace("\t", "  ")
            lines.append(redact_line(line) if redact else line)
    return lines, missing, skipped, stats


def select_source_lines(lines, project):
    """按软著常用首尾取材规则补齐固定页数。"""
    lines_per_page = int(project.get("lines_per_page", 90))
    pages = int(project.get("source_pages", 60))
    front_pages = pages // 2
    back_pages = pages - front_pages
    need = pages * lines_per_page
    selected = lines[: front_pages * lines_per_page] + lines[-back_pages * lines_per_page :]
    while len(selected) < need:
        selected.append("")
    return selected, pages, lines_per_page


def collect_source_material(repo, project, tokens=(), cli_keep_comments=False,
                            cli_keep_imports=False):
    source_material = project.get("source_material", {}) or {}
    if not isinstance(source_material, dict):
        source_material = {}
    trim_comments = bool(source_material.get("trim_comments", project.get("trim_comments", True)))
    trim_imports = bool(source_material.get("trim_imports", project.get("trim_imports", True)))
    if cli_keep_comments:
        trim_comments = False
    if cli_keep_imports:
        trim_imports = False
    max_blank_lines = max(0, min(int(source_material.get("max_blank_lines", 1)), 3))
    lines, missing, skipped, stats = read_lines(
        repo, project.get("source_files", []), project.get("redact", True), tokens,
        project.get("scrub_open_source", True), trim_comments, trim_imports, max_blank_lines,
    )
    selected, pages, lines_per_page = select_source_lines(lines, project)
    return {
        "lines": lines,
        "selected": selected,
        "pages": pages,
        "lines_per_page": lines_per_page,
        "missing": missing,
        "skipped": skipped,
        "stats": stats,
        "trim_comments": trim_comments,
        "trim_imports": trim_imports,
        "max_blank_lines": max_blank_lines,
    }


def build_source_html(project, selected_lines, pages, lines_per_page):
    """生成只包含代码页的可打印 HTML，不显示标题、页眉或页脚。"""
    font_size = float(project.get("source_font_size", 6.5))
    row_height = float(project.get("source_row_height", 8.15))
    body = []
    for page in range(pages):
        body.append('<section class="source-page">')
        chunk = selected_lines[page * lines_per_page : (page + 1) * lines_per_page]
        for line in chunk:
            text = escape(line, quote=False) if line else "&nbsp;"
            body.append(f'<div class="source-line">{text}</div>')
        body.append("</section>")
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{escape(str(project.get("name", "源程序鉴别材料")))}</title>
<style>
@page {{ size: A4 portrait; margin: 6.5mm 10mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #fff; }}
body {{ color: #111; overflow: hidden; }}
.source-page {{
  display: block;
  page-break-after: always;
  break-after: page;
  overflow: hidden;
}}
.source-page:last-child {{ page-break-after: auto; break-after: auto; }}
.source-line {{
  width: 100%;
  height: {row_height}pt;
  line-height: {row_height}pt;
  font-size: {font_size}pt;
  font-family: "SFMono-Regular", Menlo, "Noto Sans Mono CJK SC", "Noto Sans CJK SC", Consolas, monospace;
  white-space: pre;
  overflow: hidden;
  margin: 0;
  padding: 0;
}}
</style></head><body>{''.join(body)}</body></html>'''


def write_source_html(repo, project, out_path, tokens=(), cli_keep_comments=False,
                      cli_keep_imports=False):
    """从源码构建 PDF 输入 HTML，返回材料统计和输出路径。"""
    collected = collect_source_material(repo, project, tokens, cli_keep_comments, cli_keep_imports)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        build_source_html(project, collected["selected"], collected["pages"], collected["lines_per_page"]),
        encoding="utf-8",
    )
    collected["html"] = out_path
    return collected


def write_source_html_from_config(repo, config, project, out_path, cli_keep_comments=False,
                                  cli_keep_imports=False):
    tokens = own_tokens(config, repo)
    return write_source_html(repo, project, out_path, tokens, cli_keep_comments, cli_keep_imports)
