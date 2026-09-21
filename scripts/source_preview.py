#!/usr/bin/env python3
"""生成源程序鉴别材料的本地可视化预览。

预览只读取源码并对展示内容做脱敏，不上传、不修改源文件，也不会展示被判定为
第三方的文件正文。它与 generate_source_docx.py 使用同一套注释/import 裁剪规则。
"""

import argparse
import html
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from copyright_check import redact_line  # noqa: E402
from oss_scrub import own_tokens, scrub_code, third_party_reasons  # noqa: E402
from source_material import compact_blank_lines, strip_comments, strip_imports  # noqa: E402


def esc(value):
    return html.escape(str(value))


def _trim_file(text, rel, tokens, scrub=True, trim_comments=True, trim_imports=True, max_blank_lines=1):
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if scrub:
        lines, scrub_stats = scrub_code(text, tokens)
    else:
        lines, scrub_stats = raw_lines, {"header": 0, "dropped": 0}
    comment_count = 0
    import_count = 0
    if trim_comments:
        lines, comment_count = strip_comments(lines, rel)
    if trim_imports:
        lines, import_count = strip_imports(lines, rel)
    before_compact = len(lines)
    lines = compact_blank_lines(lines, max_blank_lines)
    blank_count = max(0, before_compact - len(lines))
    return {
        "raw_lines": len(raw_lines),
        "material_lines": len(lines),
        "lines": lines,
        "comments": comment_count,
        "imports": import_count,
        "blank_lines": blank_count,
        "scrub": scrub_stats,
    }


def collect_project(repo, project, tokens=(), trim_comments=True, trim_imports=True,
                    max_blank_lines=1, sample_lines=120):
    source_material = project.get("source_material", {}) or {}
    if not isinstance(source_material, dict):
        source_material = {}
    trim_comments = source_material.get("trim_comments", True) if trim_comments is None else trim_comments
    trim_imports = source_material.get("trim_imports", True) if trim_imports is None else trim_imports
    max_blank_lines = source_material.get("max_blank_lines", 1) if max_blank_lines is None else max_blank_lines
    max_blank_lines = max(0, min(int(max_blank_lines), 3))
    rows = []
    for rel in project.get("source_files", []) or []:
        path = repo / rel
        if not path.is_file():
            rows.append({"path": rel, "status": "missing", "raw_lines": 0, "material_lines": 0,
                         "comments": 0, "imports": 0, "blank_lines": 0, "sample": []})
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        reasons = third_party_reasons(rel, text, tokens)
        if reasons:
            rows.append({"path": rel, "status": "skipped", "reason": "；".join(reasons),
                         "raw_lines": len(text.splitlines()), "material_lines": 0,
                         "comments": 0, "imports": 0, "blank_lines": 0, "sample": []})
            continue
        result = _trim_file(text, rel, tokens, project.get("scrub_open_source", True),
                            trim_comments, trim_imports, max_blank_lines)
        # 只把脱敏后的样本写入 HTML，避免预览成为敏感信息副本。
        sample = [redact_line(line) for line in result.pop("lines")[:sample_lines]]
        rows.append({"path": rel, "status": "included", "sample": sample, **result})
    included = [row for row in rows if row["status"] == "included"]
    return {
        "id": project.get("id", project.get("name", "未命名项目")),
        "name": project.get("name", project.get("id", "未命名项目")),
        "source_pages": int(project.get("source_pages", 60)),
        "lines_per_page": int(project.get("lines_per_page", 90)),
        "trim_comments": bool(trim_comments),
        "trim_imports": bool(trim_imports),
        "max_blank_lines": max_blank_lines,
        "files": rows,
        "summary": {
            "total_files": len(rows),
            "included_files": len(included),
            "skipped_files": sum(row["status"] == "skipped" for row in rows),
            "missing_files": sum(row["status"] == "missing" for row in rows),
            "raw_lines": sum(row["raw_lines"] for row in rows),
            "material_lines": sum(row["material_lines"] for row in rows),
            "comments": sum(row["comments"] for row in rows),
            "imports": sum(row["imports"] for row in rows),
            "blank_lines": sum(row["blank_lines"] for row in rows),
            "estimated_pages": math.ceil(sum(row["material_lines"] for row in rows) /
                                         max(1, int(project.get("lines_per_page", 90)))),
        },
    }


def collect_config(config, repo, trim_comments=None, trim_imports=None, max_blank_lines=None, sample_lines=120):
    tokens = own_tokens(config, repo)
    return [collect_project(repo, project, tokens, trim_comments, trim_imports,
                             max_blank_lines, sample_lines)
            for project in config.get("projects", [])]


CSS = """
:root{--bg:#f5f7fb;--card:#fff;--fg:#172033;--mut:#64748b;--line:#dce3ee;--ok:#16805c;--warn:#b45309;--bad:#c0392b;--accent:#2457c5}
*{box-sizing:border-box}body{margin:0;padding:28px 18px 60px;background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1280px;margin:auto}h1{font-size:24px;margin:0 0 5px}.sub{color:var(--mut);margin-bottom:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin-bottom:18px}.stat,.card{background:var(--card);border:1px solid var(--line);border-radius:12px}.stat{padding:14px}.stat b{display:block;font-size:25px}.stat span{color:var(--mut);font-size:12px}.card{padding:18px;margin:14px 0}.head{display:flex;justify-content:space-between;gap:12px;align-items:baseline}.head h2{font-size:18px;margin:0}.meta{color:var(--mut);font-size:12px}.badge{display:inline-block;border-radius:20px;padding:2px 9px;color:#fff;font-size:12px}.ok{background:var(--ok)}.warn{background:var(--warn)}.bad{background:var(--bad)}table{border-collapse:collapse;width:100%;font-size:13px;margin-top:12px}th,td{border-bottom:1px solid var(--line);padding:7px;text-align:left;vertical-align:top}th{font-size:12px;color:var(--mut)}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#eef2f7;padding:2px 5px;border-radius:4px;word-break:break-all}.metrics{display:flex;flex-wrap:wrap;gap:18px;margin:15px 0}.metrics b{display:block;font-size:17px}.metrics span{display:block;color:var(--mut);font-size:12px}.bar{height:8px;background:var(--line);border-radius:8px;overflow:hidden;display:flex}.bar i{height:100%;display:block}.sample{background:#101828;color:#e5edf8;border-radius:8px;padding:12px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre;max-height:360px}.hint{color:var(--mut);font-size:12px;margin-top:8px}.foot{color:var(--mut);font-size:12px;margin-top:24px}
"""


def render(projects, config_path, repo, trim_comments, trim_imports, max_blank_lines):
    all_summary = [p["summary"] for p in projects]
    total = {key: sum(item[key] for item in all_summary) for key in (
        "total_files", "included_files", "skipped_files", "missing_files", "raw_lines",
        "material_lines", "comments", "imports", "blank_lines")}
    total["estimated_pages"] = sum(item["estimated_pages"] for item in all_summary)
    out = [f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>源程序材料预览</title><style>{CSS}</style></head><body><main class="wrap"><h1>源程序鉴别材料预览</h1><div class="sub">配置：<code>{esc(config_path)}</code>　源码：<code>{esc(repo)}</code>　仅显示脱敏样本，不修改源文件、不上传网络</div><section class="grid">''']
    labels = [("total_files", "选材文件"), ("included_files", "纳入文件"), ("skipped_files", "跳过第三方"),
              ("missing_files", "缺失文件"), ("raw_lines", "原始行数"), ("material_lines", "裁剪后行数"),
              ("comments", "移除注释"), ("imports", "移除导入"), ("estimated_pages", "按行估算页数")]
    for key, label in labels:
        out.append(f"<div class='stat'><b>{total[key]}</b><span>{label}</span></div>")
    out.append("</section>")
    for project in projects:
        s = project["summary"]
        status = "bad" if s["missing_files"] else ("warn" if s["skipped_files"] else "ok")
        out.append(f"<section class='card'><div class='head'><h2>{esc(project['name'])} <span class='meta'>{esc(project['id'])}</span></h2><span class='badge {status}'>{'有缺失' if status == 'bad' else '有跳过文件' if status == 'warn' else '可预览'}</span></div>")
        out.append("<div class='metrics'>")
        for key, label in [("raw_lines", "原始行数"), ("material_lines", "裁剪后行数"), ("comments", "注释裁剪"), ("imports", "导入裁剪"), ("blank_lines", "空行压缩"), ("estimated_pages", "按行估算页数")]:
            out.append(f"<div><b>{s[key]}</b><span>{label}</span></div>")
        out.append(f"</div><div class='bar'><i style='width:{min(100, s['material_lines'] / max(1, s['raw_lines']) * 100):.1f}%;background:var(--accent)'></i></div><div class='hint'>配置页数：{project['source_pages']} 页 × {project['lines_per_page']} 行；当前按裁剪后代码估算 {s['estimated_pages']} 页。裁剪策略：注释={'开启' if project['trim_comments'] else '关闭'}、import/include/use={'开启' if project['trim_imports'] else '关闭'}、最多连续空行={project['max_blank_lines']}</div>")
        out.append("<table><tr><th>文件</th><th>状态</th><th>原始行数</th><th>材料行数</th><th>注释</th><th>导入</th><th>操作</th></tr>")
        for row in project["files"]:
            if row["status"] == "included":
                action = f"<details><summary>查看脱敏样本</summary><pre class='sample'>{esc(chr(10).join(row['sample']))}</pre></details>"
                status_text = "纳入"
            elif row["status"] == "skipped":
                action = f"<span class='hint'>{esc(row.get('reason', ''))}</span>"
                status_text = "跳过"
            else:
                action, status_text = "—", "缺失"
            out.append(f"<tr><td><code>{esc(row['path'])}</code></td><td>{status_text}</td><td>{row['raw_lines']}</td><td>{row['material_lines']}</td><td>{row['comments']}</td><td>{row['imports']}</td><td>{action}</td></tr>")
        out.append("</table></section>")
    out.append("<div class='foot'>提示：预览只用于人工确认选材和裁剪效果；正式生成 DOCX 前仍需执行版权检查、敏感信息检查和页数校验。</div></main></body></html>")
    return "\n".join(out)


def write_preview(config, config_path, repo, out_path, trim_comments=None, trim_imports=None,
                  max_blank_lines=None, sample_lines=120, json_path=None):
    projects = collect_config(config, repo, trim_comments, trim_imports, max_blank_lines, sample_lines)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(projects, config_path, repo, trim_comments, trim_imports, max_blank_lines), encoding="utf-8")
    if json_path:
        json_path = Path(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({"projects": projects}, ensure_ascii=False, indent=2), encoding="utf-8")
    return projects


def main():
    ap = argparse.ArgumentParser(description="生成源程序鉴别材料的本地可视化预览")
    ap.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", help="HTML 输出路径；默认写到 output_root/源程序材料预览.html")
    ap.add_argument("--json", help="同时输出统计 JSON")
    ap.add_argument("--sample-lines", type=int, default=120, help="每个文件最多展示多少行脱敏样本")
    ap.add_argument("--keep-comments", action="store_true")
    ap.add_argument("--keep-imports", action="store_true")
    args = ap.parse_args()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else Path(config.get("output_root", "soft-copyright-materials")) / "源程序材料预览.html"
    max_blank_lines = None
    write_preview(config, config_path, Path(args.repo).resolve(), out,
                  False if args.keep_comments else None,
                  False if args.keep_imports else None, max_blank_lines,
                  max(1, args.sample_lines), args.json)
    print(out.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
