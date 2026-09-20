#!/usr/bin/env python3
"""整理说明书截图，生成《截图清单.json》，供 generate_docs.py 插入对应功能章节。

截图有三种来源，都归到同一个清单：
1. 用户自己截的图：放进 <材料目录>/用户截图/，文件名带模块名或序号即可
2. Claude 用内置浏览器截的图（Web 项目跑起来后逐页截，另存到同一目录）
3. 明确不放截图：说明书保留“【截图预留：模块名】”文字，审查时一眼能看出缺哪张

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


def main():
    ap = argparse.ArgumentParser(description="整理说明书截图并生成清单")
    ap.add_argument("--materials", required=True, help="某份软著的材料目录")
    ap.add_argument("--src", default="用户截图", help="原始截图目录（相对材料目录）")
    ap.add_argument("--spec", help="说明书素材.json，用于把截图和模块对应起来")
    ap.add_argument("--prefix", default="7", help="截图编号所属章节号（默认功能模块章 7）")
    args = ap.parse_args()

    root = Path(args.materials)
    src = root / args.src
    dst = root / "截图"
    modules = []
    if args.spec and Path(args.spec).exists():
        modules = [p["module"] for p in json.loads(Path(args.spec).read_text(encoding="utf-8"))["pages"]]

    images = sorted([p for p in src.glob("*") if p.suffix.lower() in IMG_EXT], key=sort_key) if src.exists() else []
    dst.mkdir(parents=True, exist_ok=True)
    items = []
    for i, p in enumerate(images, 1):
        mod = match_module(p.name, modules)
        out_name = f"{args.prefix}-{i}{('_' + mod) if mod else ''}{p.suffix.lower()}"
        shutil.copy2(p, dst / out_name)
        items.append({"no": f"图 {args.prefix}-{i}", "file": f"截图/{out_name}",
                      "module": mod, "title": mod or Path(p.stem).name, "source": str(p.name)})

    (root / "截图清单.json").write_text(json.dumps(
        {"count": len(items), "unmatched": [i["no"] for i in items if not i["module"]], "items": items},
        ensure_ascii=False, indent=2), encoding="utf-8")

    if not images:
        print(f"{src} 下没有图片：说明书将保留“【截图预留：模块名】”占位文字。")
        print("放图方式：①自己截图放进该目录；②Web 项目可让 Claude 用内置浏览器逐页截图另存到该目录。")
    else:
        print(f"整理 {len(items)} 张截图 → {dst}")
        unmatched = [i["no"] for i in items if not i["module"]]
        if unmatched:
            print(f"未对上模块的截图：{'、'.join(unmatched)}（在文件名里加模块名，或手工改 截图清单.json 的 module 字段）")
    print(root / "截图清单.json")


if __name__ == "__main__":
    main()
