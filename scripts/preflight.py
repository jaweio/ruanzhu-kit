#!/usr/bin/env python3
"""ruanzhu-kit 环境预检。

预检只读取本机环境和配置，不启动项目、不上传材料。它把“生成 DOCX/PDF、读取 PDF、
浏览器填表”所需依赖分成 required / optional，并提供 JSON 结果供看板和 CI 使用。

示例：
  python3 scripts/preflight.py --config soft-copyright-materials/ruanzhu.config.json
  python3 scripts/preflight.py --config ... --include-browser --strict
"""

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _which(env_name, names):
    override = os.environ.get(env_name)
    if override and Path(override).is_file():
        return override
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    mac_candidates = {
        "RUANZHU_CHROME": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
    }
    for candidate in mac_candidates.get(env_name, []):
        if Path(candidate).is_file():
            return candidate
    return None


def _module(name):
    return importlib.util.find_spec(name) is not None


def _font():
    names = ("PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", "SimSun", "Arial Unicode MS")
    fc_match = shutil.which("fc-match")
    if fc_match:
        for name in names:
            try:
                result = subprocess.run([fc_match, name], capture_output=True, text=True, timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0]
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Microsoft YaHei.ttf",
    ]
    return next((path for path in candidates if Path(path).exists()), None)


def check(*, include_browser=False, config_path=None):
    checks = []

    def add(name, ok, required, detail, fix=""):
        checks.append({"name": name, "ok": bool(ok), "required": required,
                       "detail": detail, "fix": fix})

    add("python", sys.version_info >= (3, 10), True, platform.python_version(), "使用 Python 3.10 或更高版本")
    add("python-docx", _module("docx"), True,
        "已安装" if _module("docx") else "未安装",
        "python -m pip install -r requirements.txt")
    pdf_reader = _module("pypdf") or bool(shutil.which("pdftotext"))
    add("pdf-reader", pdf_reader, True,
        "pypdf" if _module("pypdf") else ("pdftotext" if shutil.which("pdftotext") else "未找到 pypdf 或 pdftotext"),
        "python -m pip install -r requirements.txt，或安装 Poppler")
    photo_pdf = _module("PIL") and _module("reportlab")
    add("photo-to-a4-pdf", photo_pdf, False,
        "Pillow + ReportLab 已安装" if photo_pdf else "未安装 Pillow 或 ReportLab",
        "python -m pip install -r requirements.txt")
    pandoc = _which("RUANZHU_PANDOC", ["pandoc"])
    add("pandoc", pandoc, True, pandoc or "未找到 pandoc", "安装 Pandoc 并加入 PATH")
    chrome = _which("RUANZHU_CHROME", ["google-chrome", "chromium", "chromium-browser"])
    add("chromium", chrome, True, chrome or "未找到 Chrome/Chromium", "安装 Chrome/Chromium，或设置 RUANZHU_CHROME")
    pdfinfo = _which("RUANZHU_PDFINFO", ["pdfinfo"])
    add("pdfinfo", pdfinfo, False, pdfinfo or "未找到（将使用 PDF 对象回退计页）", "安装 Poppler 可提高页数检测稳定性")
    font = _font()
    add("cjk-font", font, True, font or "未找到中文字体", "安装 PingFang SC、Noto Sans CJK SC 或 Microsoft YaHei")

    if include_browser:
        node = _which("RUANZHU_NODE", ["node"])
        playwright = _module("playwright")
        add("node", node, True, node or "未找到 node", "安装 Node.js 18 或更高版本")
        add("playwright", playwright, True, "已安装" if playwright else "未安装",
            "在 scripts/auto-fill 目录执行 npm install playwright")
    else:
        add("browser-automation", True, False, "未检查（默认使用浏览器插件或 Computer Use）")

    if config_path:
        path = Path(config_path)
        valid = path.is_file()
        detail = str(path) if valid else f"配置不存在：{path}"
        add("config", valid, True, detail, "先运行 create_config.py 生成 ruanzhu.config.json")

    return {"ok": not any(not item["ok"] and item["required"] for item in checks),
            "checks": checks}


def main():
    parser = argparse.ArgumentParser(description="ruanzhu-kit 环境预检")
    parser.add_argument("--config", help="可选：ruanzhu.config.json")
    parser.add_argument("--include-browser", action="store_true", help="同时检查 Node/Playwright 备用填表脚本")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--strict", action="store_true", help="required 项缺失时返回退出码 1")
    args = parser.parse_args()
    result = check(include_browser=args.include_browser, config_path=args.config)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["checks"]:
            mark = "OK" if item["ok"] else ("缺失" if item["required"] else "可选")
            print(f"[{mark}] {item['name']}: {item['detail']}")
            if not item["ok"] and item["fix"]:
                print(f"      修复：{item['fix']}")
        print("预检通过" if result["ok"] else "预检未通过：请先处理 required 项")
    return 0 if result["ok"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
