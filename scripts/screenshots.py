#!/usr/bin/env python3
"""整理说明书截图，生成《截图清单.json》，供 generate_docs.py 插入对应功能章节。

截图有三种来源，都归到同一个清单：
1. 用户自己截的图：放进 <材料目录>/用户截图/，文件名带模块名或序号即可
2. Claude 用内置浏览器截的图（Web 项目跑起来后逐页截，另存到同一目录）
3. 明确不放截图：说明书不出现图位和任何“截图预留”文字；缺图只记录在内部清单和看板

脚本只做整理：按文件名里的序号/模块名排序、与说明书素材里的模块对上号、复制到 截图/ 目录，
不改图片内容，也不会凭空生成截图。

用法：
  python3 screenshots.py --materials soft-copyright-materials/01-XXX软件
  python3 screenshots.py --materials <目录> --spec soft-copyright-materials/说明书素材.json
"""

import argparse
import json
import re
import shutil
from pathlib import Path

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def sort_key(p):
    m = re.match(r"^(\d+)", p.stem)
    return (0, int(m.group(1)), p.stem) if m else (1, 0, p.stem)


def match_module(name, modules):
    """按文件名里出现的模块名归类；对不上就留空，由人工填。"""
    stem = re.sub(r"^[\d\-_.\s]+", "", Path(name).stem)
    for mod in modules:
        if mod and (mod in stem or stem in mod):
            return mod
    return ""


def load_modules(spec_path):
    data = load_spec(spec_path)
    return [str(page.get("module", "")).strip() for page in data.get("pages", [])
            if isinstance(page, dict) and str(page.get("module", "")).strip()]


def load_spec(spec_path):
    if not spec_path or not Path(spec_path).exists():
        return {}
    try:
        return json.loads(Path(spec_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_evidence(spec_path):
    data = load_spec(spec_path)
    return [item for item in data.get("evidence_plan", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()]


def match_evidence(name, evidence):
    """用稳定 ID 或少量标题关键词识别后端证据截图。"""
    stem = Path(name).stem.lower()
    for item in evidence:
        evidence_id = str(item.get("id", "")).lower()
        title = str(item.get("title", "")).lower()
        if evidence_id and evidence_id in stem:
            return evidence_id
        tokens = {
            "api-docs": ("knife4j", "swagger", "openapi", "api-doc", "接口文档"),
            "api-success": ("api-success", "success", "成功响应", "成功返回"),
            "api-error": ("api-error", "error", "错误响应", "异常返回", "4xx"),
            "runtime-log": ("runtime-log", "log", "日志", "启动日志"),
        }.get(evidence_id, ())
        if any(token in stem for token in tokens):
            return evidence_id
        if title and title in stem:
            return evidence_id
    return ""


def validate_manifest(root, spec_path=None):
    """只校验截图材料，不访问浏览器，也不替用户生成截图。"""
    manifest_path = root / "截图清单.json"
    report = {"manifest": str(manifest_path), "exists": manifest_path.exists(),
              "missing_files": [], "invalid_files": [], "unmatched_items": [],
              "missing_modules": [], "missing_evidence": [], "count": 0, "ok": False}
    if not manifest_path.exists():
        return report
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report["invalid_manifest"] = True
        return report
    items = manifest.get("items") if isinstance(manifest, dict) else []
    if not isinstance(items, list):
        report["invalid_manifest"] = True
        return report
    report["count"] = len(items)
    seen = set()
    modules_in_items = set()
    for item in items:
        if not isinstance(item, dict):
            report["invalid_files"].append("<非对象条目>")
            continue
        file_name = str(item.get("file", "")).strip()
        if not file_name or Path(file_name).is_absolute() or ".." in Path(file_name).parts:
            report["invalid_files"].append(file_name or "<空路径>")
            continue
        if file_name in seen:
            report["invalid_files"].append(f"重复：{file_name}")
        seen.add(file_name)
        target = root / file_name
        if not target.is_file():
            report["missing_files"].append(file_name)
        elif target.stat().st_size <= 0:
            report["invalid_files"].append(f"空文件：{file_name}")
        module = str(item.get("module", "")).strip()
        if module:
            modules_in_items.add(module)
        else:
            report["unmatched_items"].append(str(item.get("no", file_name)))
    modules = load_modules(spec_path)
    report["missing_modules"] = [module for module in modules if module not in modules_in_items]
    evidence = load_evidence(spec_path)
    evidence_in_items = {str(item.get("evidence_id", "")).strip() for item in items
                         if isinstance(item, dict) and str(item.get("evidence_id", "")).strip()}
    report["missing_evidence"] = [str(item.get("id")) for item in evidence
                                   if item.get("required", True) and str(item.get("id")) not in evidence_in_items]
    report["ok"] = bool(report["exists"]) and not any(
        report[key] for key in ("missing_files", "invalid_files", "unmatched_items", "missing_modules", "missing_evidence")
    )
    return report


def main():
    ap = argparse.ArgumentParser(description="整理说明书截图并生成清单")
    ap.add_argument("--materials", required=True, help="某份软著的材料目录")
    ap.add_argument("--src", default="用户截图", help="原始截图目录（相对材料目录）")
    ap.add_argument("--spec", help="说明书素材.json，用于把截图和模块对应起来")
    ap.add_argument("--prefix", default="7", help="截图编号所属章节号（默认功能模块章 7）")
    ap.add_argument("--check", action="store_true", help="只校验现有截图清单与文件，不复制文件")
    ap.add_argument("--fail-on-missing", action="store_true", help="校验失败时返回非零状态")
    args = ap.parse_args()

    root = Path(args.materials)
    if args.check:
        report = validate_manifest(root, args.spec)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] or not args.fail_on_missing else 1
    src = root / args.src
    dst = root / "截图"
    modules = []
    evidence = []
    if args.spec and Path(args.spec).exists():
        spec = load_spec(args.spec)
        modules = [p["module"] for p in spec.get("pages", []) if isinstance(p, dict) and p.get("module")]
        evidence = load_evidence(args.spec)

    images = sorted([p for p in src.glob("*") if p.suffix.lower() in IMG_EXT], key=sort_key) if src.exists() else []
    dst.mkdir(parents=True, exist_ok=True)
    items = []
    for i, p in enumerate(images, 1):
        mod = match_module(p.name, modules)
        evidence_id = match_evidence(p.name, evidence)
        out_name = f"{args.prefix}-{i}{('_' + mod) if mod else ''}{p.suffix.lower()}"
        shutil.copy2(p, dst / out_name)
        item = {"no": f"图 {args.prefix}-{i}", "file": f"截图/{out_name}",
                "module": mod, "title": mod or Path(p.stem).name, "source": str(p.name)}
        if evidence_id:
            item["evidence_id"] = evidence_id
        items.append(item)

    (root / "截图清单.json").write_text(json.dumps(
        {"count": len(items), "unmatched": [i["no"] for i in items if not i["module"]], "items": items},
        ensure_ascii=False, indent=2), encoding="utf-8")

    if not images:
        print(f"{src} 下没有图片：说明书不会插入图位；如需截图请补齐真实截图后重跑 generate_docs.py。")
        print("放图方式：①自己截图放进该目录；②Web 项目可让 Claude 用内置浏览器逐页截图另存到该目录。")
    else:
        print(f"整理 {len(items)} 张截图 → {dst}")
        unmatched = [i["no"] for i in items if not i["module"]]
        if unmatched:
            print(f"未对上模块的截图：{'、'.join(unmatched)}（在文件名里加模块名，或手工改 截图清单.json 的 module 字段）")
    print(root / "截图清单.json")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
