#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path
from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from copyright_check import redact_line  # noqa: E402
from oss_scrub import own_tokens, scrub_code, third_party_reasons  # noqa: E402


def set_cell_no_wrap(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(OxmlElement("w:noWrap"))


def set_cell_margins(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin in ("top", "left", "bottom", "right"):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), "0")
        node.set(qn("w:type"), "dxa")


def remove_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        elem = borders.find(qn(f"w:{edge}"))
        if elem is None:
            elem = OxmlElement(f"w:{edge}")
            borders.append(elem)
        elem.set(qn("w:val"), "nil")


def fixed_layout(table):
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.first_child_found_in("w:tblLayout")
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")


def read_lines(repo, files, redact=True, tokens=(), scrub=True):
    """读取取材文件：跳过第三方文件，清除自有代码的开源/仓库痕迹，脱敏敏感信息。"""
    lines, missing, skipped = [], [], []
    stats = {"headers": 0, "dropped": 0}
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
            file_lines, st = scrub_code(text, tokens)
            stats["headers"] += st["header"]
            stats["dropped"] += st["dropped"]
        else:
            file_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for line in file_lines:
            line = line.replace("\t", "  ")
            lines.append(redact_line(line) if redact else line)
    return lines, missing, skipped, stats


def add_page(doc, page_lines, lines_per_page, font_size_pt, row_height_pt):
    table = doc.add_table(rows=lines_per_page, cols=1)
    table.autofit = False
    remove_borders(table)
    fixed_layout(table)
    for i, row in enumerate(table.rows):
        row.height = Pt(row_height_pt)
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        cell = row.cells[0]
        cell.width = Cm(19)
        set_cell_no_wrap(cell)
        set_cell_margins(cell)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(page_lines[i] or " ")
        run.font.size = Pt(font_size_pt)


def build_doc(repo, out_root, project, tokens=()):
    lines_per_page = int(project.get("lines_per_page", 90))
    pages = int(project.get("source_pages", 60))
    front_pages = pages // 2
    back_pages = pages - front_pages
    font_size = float(project.get("source_font_size", 6.5))
    row_height = float(project.get("source_row_height", 8.15))
    redact = project.get("redact", True)
    scrub = project.get("scrub_open_source", True)
    lines, missing, skipped, scrub_stats = read_lines(repo, project.get("source_files", []), redact, tokens, scrub)
    need = pages * lines_per_page
    if skipped:
        print(f"[{project['name']}] 跳过 {len(skipped)} 个第三方文件：" + "、".join(r for r, _ in skipped), file=sys.stderr)
    if len(lines) < need:
        print(f"[{project['name']}] 警告：可用代码 {len(lines)} 行，不足 {need} 行（{pages} 页），请补充自研文件",
              file=sys.stderr)
    selected = lines[: front_pages * lines_per_page] + lines[-back_pages * lines_per_page :]
    while len(selected) < pages * lines_per_page:
        selected.append("")

    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(0.65)
    section.bottom_margin = Cm(0.65)
    section.left_margin = Cm(1)
    section.right_margin = Cm(1)

    for page in range(pages):
        chunk = selected[page * lines_per_page : (page + 1) * lines_per_page]
        add_page(doc, chunk, lines_per_page, font_size, row_height)
        if page < pages - 1:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    out_dir = out_root / project["id"] / "源程序提取"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"源程序鉴别材料-{pages}页.docx"
    doc.save(out_path)
    (out_dir / "源程序DOCX生成报告.md").write_text(
        f"# {project['name']} 源程序 DOCX 生成报告\n\n"
        f"- 输出文件：`{out_path.name}`\n"
        f"- 页面方向：竖向 A4\n"
        f"- 页数：{pages}\n"
        f"- 每页代码行数：{lines_per_page}\n"
        f"- 缺失文件：{'、'.join(missing) if missing else '无'}\n"
        f"- 敏感信息脱敏：{'已开启（密钥/手机号/邮箱/内网 IP）' if redact else '未开启'}\n"
        f"- 开源痕迹清除：{'已开启' if scrub else '未开启'}（删除自有许可证/版权头 {scrub_stats['headers']} 处，"
        f"含仓库地址或开源字样的注释行 {scrub_stats['dropped']} 行）\n"
        f"- 自动跳过的第三方文件：{len(skipped)} 个\n"
        + "".join(f"  - `{r}`：{why}\n" for r, why in skipped)
        + f"- 可用代码行数：{len(lines)}（需要 {need}）\n",
        encoding="utf-8",
    )
    print(out_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out_root = Path(cfg.get("output_root", "soft-copyright-materials"))
    repo = Path(args.repo)
    tokens = own_tokens(cfg, repo)
    for project in cfg["projects"]:
        build_doc(repo, out_root, project, tokens)


if __name__ == "__main__":
    main()

