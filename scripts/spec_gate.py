#!/usr/bin/env python3
"""Step 0 闸门：核对按需求新建的 uni-app 项目是否真实实现了产品规格。

只读检查，不生成代码、不启动项目：
- 规格中每个页面都登记在 pages.json（含分包），且对应 .vue/.nvue 不是空壳；
- 自有有效代码行数足够支撑源程序材料（默认 3000 行 ≈ 60 页 × 50 行）；
- 重复代码占比不过高（防止复制粘贴凑行数）；
- 可选：H5 构建产物存在（--require-build）。
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

CODE_EXT = {".vue", ".nvue", ".js", ".ts", ".uts", ".scss", ".css", ".less"}
SKIP_DIRS = {"node_modules", "unpackage", "dist", "uni_modules", ".git", ".hbuilderx", "static"}
DEFAULT_MIN_LINES = 3000
DEFAULT_MIN_PAGE_LINES = 30
DEFAULT_MAX_DUP_RATIO = 0.30


def strip_json_comments(text):
    """pages.json 允许 // 和 /* */ 注释（uni-app 条件编译），解析前去掉。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r'(^|[^:"\\])//.*$', r"\1", text, flags=re.M)


def registered_pages(project):
    path = project / "pages.json"
    if not path.is_file():
        path = project / "src" / "pages.json"
    if not path.is_file():
        return None, project
    data = json.loads(strip_json_comments(path.read_text(encoding="utf-8")))
    pages = {p["path"] for p in data.get("pages", []) if "path" in p}
    for sub in data.get("subPackages", data.get("subpackages", [])):
        pages |= {f"{sub['root'].rstrip('/')}/{p['path']}" for p in sub.get("pages", []) if "path" in p}
    return pages, path.parent


def effective_lines(text):
    """去掉空行和纯注释行后的代码行。"""
    lines, in_block = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if in_block:
            if "*/" in line or "-->" in line:
                in_block = False
            continue
        if not line or line.startswith("//"):
            continue
        if line.startswith("/*") or line.startswith("<!--"):
            in_block = "*/" not in line and "-->" not in line
            continue
        lines.append(line)
    return lines


def source_files(root):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in CODE_EXT and not SKIP_DIRS & set(path.relative_to(root).parts):
            yield path


def check(project, spec, min_lines=DEFAULT_MIN_LINES, min_page_lines=DEFAULT_MIN_PAGE_LINES,
          max_dup_ratio=DEFAULT_MAX_DUP_RATIO, require_build=False):
    project = Path(project)
    errors, warnings = [], []
    pages, src_root = registered_pages(project)
    if pages is None:
        return {"ok": False, "errors": ["不是 uni-app 项目：找不到 pages.json"], "warnings": [], "modules": []}

    modules, spec_pages = [], set()
    for module in spec.get("modules", []):
        rows = []
        for page in module.get("pages", []):
            page = page.strip("/")
            spec_pages.add(page)
            file = next((src_root / f"{page}{ext}" for ext in (".vue", ".nvue", ".uvue")
                         if (src_root / f"{page}{ext}").is_file()), None)
            count = len(effective_lines(file.read_text(encoding="utf-8"))) if file else 0
            row = {"page": page, "registered": page in pages, "file": str(file or ""), "lines": count}
            if not row["registered"]:
                errors.append(f"{module['name']}：页面 {page} 未登记在 pages.json")
            if not file:
                errors.append(f"{module['name']}：页面文件 {page}.vue 不存在")
            elif count < min_page_lines:
                errors.append(f"{module['name']}：{page} 只有 {count} 行有效代码，像空壳页面（至少 {min_page_lines} 行）")
            rows.append(row)
        if not rows:
            errors.append(f"{module.get('name', '未命名模块')}：规格没有列出页面，无法核对是否实现")
        modules.append({"name": module.get("name", ""), "pages": rows})
    if not modules:
        errors.append("产品规格没有模块")
    for extra in sorted(pages - spec_pages):
        warnings.append(f"pages.json 中的 {extra} 不在规格内：确认是否属于本软著，否则不要写进说明书")

    all_lines, per_file = [], {}
    for path in source_files(src_root):
        lines = effective_lines(path.read_text(encoding="utf-8", errors="ignore"))
        per_file[str(path.relative_to(project))] = len(lines)
        all_lines.extend(lines)
    total = len(all_lines)
    if total < min_lines:
        errors.append(f"自有有效代码 {total} 行，不足 {min_lines} 行；请实现更多真实功能或如实提交较少页数，不得凑行数")
    # 只统计有实际内容的行，避免把 `}`、`</view>` 这类结构行算成重复
    substantive = [l for l in all_lines if len(l) >= 20]
    counts = Counter(substantive)
    dup = sum(n - 1 for n in counts.values() if n > 1)
    dup_ratio = dup / len(substantive) if substantive else 0.0
    if dup_ratio > max_dup_ratio:
        errors.append(f"重复代码占 {dup_ratio:.0%}，超过 {max_dup_ratio:.0%}；疑似复制粘贴凑行数")
    if require_build and not any((project / p / "index.html").is_file()
                                 for p in ("dist/build/h5", "unpackage/dist/build/web", "unpackage/dist/build/h5")):
        errors.append("没有找到 H5 构建产物；先完成构建并确认能运行，再生成材料")
    return {
        "ok": not errors, "errors": errors, "warnings": warnings, "modules": modules,
        "code_lines": total, "estimated_pages": total // 50, "dup_ratio": round(dup_ratio, 3), "files": per_file,
    }


def main():
    parser = argparse.ArgumentParser(description="Step 0：核对按需求新建的 uni-app 项目是否真实实现产品规格")
    parser.add_argument("--project", required=True, help="uni-app 项目目录")
    parser.add_argument("--spec", required=True, help="产品规格.json")
    parser.add_argument("--min-lines", type=int, default=DEFAULT_MIN_LINES)
    parser.add_argument("--min-page-lines", type=int, default=DEFAULT_MIN_PAGE_LINES)
    parser.add_argument("--max-dup-ratio", type=float, default=DEFAULT_MAX_DUP_RATIO)
    parser.add_argument("--require-build", action="store_true", help="要求存在 H5 构建产物")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    result = check(args.project, spec, args.min_lines, args.min_page_lines, args.max_dup_ratio, args.require_build)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for m in result["modules"]:
            print(f"{m['name']}：" + "，".join(f"{p['page']}（{p['lines']} 行）" for p in m["pages"]))
        if "code_lines" in result:
            print(f"有效代码 {result['code_lines']} 行，约 {result['estimated_pages']} 页；重复占比 {result['dup_ratio']:.0%}")
        for w in result["warnings"]:
            print(f"⚠️ {w}")
        for e in result["errors"]:
            print(f"❌ {e}")
        print("Step 0 闸门通过，可进入 Step 1" if result["ok"] else "Step 0 闸门未通过")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
