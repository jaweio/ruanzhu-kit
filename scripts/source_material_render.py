#!/usr/bin/env python3
"""源程序鉴别材料的共享读取与 HTML 打印模板。

DOCX 和 PDF 都必须使用同一份裁剪、脱敏后的代码行，避免两个提交件内容不一致。
PDF 路径不依赖 python-docx 或办公软件，交给 Chromium 负责分页和打印。
"""

from __future__ import annotations

import math

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


MIN_LINES_PER_PAGE = 50
# 版式参照已成功登记的源程序材料：A4 竖向，五号字（10.5pt）、行距 14.5pt、每页 50 行排满；
# 页边距 上 25mm（含页码）/ 下 16mm / 左 25mm / 右 23mm。
MARGIN_MM = {"top": 25, "right": 23, "bottom": 16, "left": 25}
BASE_FONT_PT = 10.5
BASE_ROW_PT = 14.5
PAGE_BODY_HEIGHT_PT = (297 - MARGIN_MM["top"] - MARGIN_MM["bottom"]) / 25.4 * 72
PAGE_BODY_WIDTH_PT = (210 - MARGIN_MM["left"] - MARGIN_MM["right"]) / 25.4 * 72
FONT_STACK = '"Helvetica Neue", Helvetica, Arial, "Songti SC", STSong, SimSun, serif'
_FONT_FILES = ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc",
               "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")
_measure_cache = {}


def page_lines(project):
    """每页代码行数：默认且至少 50 行。"""
    return max(MIN_LINES_PER_PAGE, int(project.get("lines_per_page", MIN_LINES_PER_PAGE)))


def page_metrics(project, selected_lines=None):
    """行高 = 可用高度 ÷ 每页行数（50 行时约 14.5pt），每页从上排到下；字号五号 10.5pt，
    每页行数更多时按比例缩小。长行不缩字号，改为折行（见 wrap_rows）。"""
    per_page = page_lines(project)
    row_height = round(min(BASE_ROW_PT, PAGE_BODY_HEIGHT_PT / per_page), 2)
    font_size = float(project.get("source_font_size") or round(BASE_FONT_PT * row_height / BASE_ROW_PT, 2))
    return row_height, round(min(font_size, row_height * 0.8), 2)


def _measurer(font_size):
    """返回测量字符串宽度（pt）的函数：优先用与 PDF 相同的 Helvetica 字体实测，找不到时按均值估算。"""
    if font_size in _measure_cache:
        return _measure_cache[font_size]
    font = None
    try:
        from PIL import ImageFont
        for path in _FONT_FILES:
            if Path(path).is_file():
                font = ImageFont.truetype(path, size=100)
                break
    except (ImportError, OSError):
        font = None

    def width(text):
        total = 0.0
        latin = []
        for ch in text:
            if ord(ch) >= 0x2E80:  # 中日韩字符按全角
                total += font_size
            else:
                latin.append(ch)
        run = "".join(latin)
        if run:
            total += (font.getlength(run) / 100 * font_size) if font else len(run) * font_size * 0.56
        return total
    _measure_cache[font_size] = width
    return width


def wrap_rows(lines, font_size, width_pt=PAGE_BODY_WIDTH_PT):
    """把超出页宽的代码行折成多行显示；折出的每一行都计入每页 50 行，代码一字不丢。"""
    width = _measurer(font_size)
    limit = width_pt * 0.97  # 预留余量，避免浏览器字形微差导致溢出
    rows = []
    for line in lines:
        line = line.replace("\t", "    ")
        while width(line) > limit:
            lo, hi = 1, len(line)
            while lo < hi:  # 二分找能放下的最长前缀
                mid = (lo + hi + 1) // 2
                if width(line[:mid]) <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            cut = lo
            space = max(line.rfind(" ", 0, cut), line.rfind(",", 0, cut) + 1)
            if space > cut * 0.6:  # 尽量在空格或逗号处断开，避免把单词拆开
                cut = space
            rows.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        rows.append(line)
    return rows


def select_source_lines(lines, project):
    """按软著首尾取材规则选取源程序行。

    代码超过配置页数时取前 N/2 页和后 N/2 页；不足时全部提交、按实际页数计，
    绝不重复代码、绝不补空行凑页数。
    """
    lines_per_page = page_lines(project)
    pages = int(project.get("source_pages", 60))
    if len(lines) <= pages * lines_per_page:
        return list(lines), max(1, math.ceil(len(lines) / lines_per_page)), lines_per_page
    front_pages = pages // 2
    back_pages = pages - front_pages
    selected = lines[: front_pages * lines_per_page] + lines[-back_pages * lines_per_page :]
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
    max_blank_lines = max(0, min(int(source_material.get("max_blank_lines", 0)), 3))
    lines, missing, skipped, stats = read_lines(
        repo, project.get("source_files", []), project.get("redact", True), tokens,
        project.get("scrub_open_source", True), trim_comments, trim_imports, max_blank_lines,
    )
    # 选材按“显示行”计：长行先折行，每页正好 50 行（含折行），首尾取材和页数都以此为准
    rows = wrap_rows(lines, page_metrics(project)[1])
    selected, pages, lines_per_page = select_source_lines(rows, project)
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
    row_height, font_size = page_metrics(project)
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
@page {{ size: A4 portrait; margin: {MARGIN_MM["top"]}mm {MARGIN_MM["right"]}mm {MARGIN_MM["bottom"]}mm {MARGIN_MM["left"]}mm;
  @top-right {{ content: counter(page); font-size: 9pt; color: #555; }}
}}
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
  font-family: {FONT_STACK};
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


def expected_source_pages(project_dir, project):
    """源程序 PDF 应有页数：代码不足配置页数且已全部提交时，以实际页数为准。"""
    configured = int(project.get("source_pages", 60))
    record = Path(project_dir) / "源程序提取" / "源程序取材记录.json"
    try:
        import json
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return configured, False
    if data.get("complete") is True and isinstance(data.get("pages"), int) and 0 < data["pages"] <= configured:
        return data["pages"], True
    return configured, False
