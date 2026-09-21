#!/usr/bin/env python3
"""朱雀风格 AIGC 检测辅助。

这是一个显式触发的联网检查器：默认本地离线检查仍由 aigc_check.py 完成。
API Key 只从环境变量或 macOS Keychain 读取，绝不写入项目、配置文件或报告。
"""

import argparse
import hashlib
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

CONSOLE_URL = "https://console.cloud.tencent.com/edgeone/makers?tab=models&subTab=apikey"
DEFAULT_BASE_URL = "https://ai-gateway.edgeone.link/v1"
DEFAULT_MODEL = "@makers/deepseek-v4-flash"
KEYCHAIN_SERVICE = "ruanzhu-kit.zhusque"
KEYCHAIN_ACCOUNT = "MAKERS_MODELS_KEY"
ENV_NAMES = ("MAKERS_MODELS_KEY", "RUANZHU_ZHUSQUE_API_KEY")
DEFAULT_CHUNK_CHARS = 12000
CACHE_VERSION = "zhusque-cache-v1"
FINAL_MARKER = ".zhusque-final.json"
SKIP_NAMES = {
    "AIGC检测报告.md", "AIGC改写任务单.md", "朱雀检测报告.md",
    "版权风险检查报告.md", "待补充信息清单.md", "截图证据计划.md", "源码材料清单.md", FINAL_MARKER,
}


def setup_hint():
    return (
        "未绑定朱雀检测 Key。请先在腾讯 EdgeOne Makers 控制台生成 API Key：\n"
        f"{CONSOLE_URL}\n\n"
        "生成后运行：\n"
        "  python3 <skill目录>/scripts/zhusque_check.py bind\n"
        "Key 只会保存到本机 macOS Keychain，不会写入仓库。"
    )


def keychain_available():
    return sys.platform == "darwin" and shutil.which("security") is not None


def keychain_get():
    if not keychain_available():
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
         "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def keychain_bind(key):
    if not keychain_available():
        raise RuntimeError("当前系统没有可用的 macOS Keychain；请使用 MAKERS_MODELS_KEY 环境变量。")
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
         "-a", KEYCHAIN_ACCOUNT, "-w"],
        input=f"{key}\n{key}\n",
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("写入 macOS Keychain 失败，请检查钥匙串权限。")


def keychain_unbind():
    if not keychain_available():
        return False
    result = subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE,
         "-a", KEYCHAIN_ACCOUNT],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def resolve_key():
    for name in ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"环境变量 {name}"
    value = keychain_get()
    if value:
        return value, "macOS Keychain"
    return None, None


def validate_key(key):
    if not key or "\n" in key or "\r" in key:
        raise ValueError("Key 为空或包含换行。")
    if len(key) < 20:
        raise ValueError("Key 长度过短，请粘贴完整的 API Key。")


def bind(args):
    if args.open:
        webbrowser.open(CONSOLE_URL)
    print(setup_hint().split("\n\n")[0])
    print(CONSOLE_URL)
    if args.stdin:
        key = sys.stdin.read().strip()
    else:
        key = getpass.getpass("粘贴 API Key（输入不会回显）：")
    validate_key(key)
    keychain_bind(key)
    print("已绑定到本机 macOS Keychain；不会把 Key 写入仓库、配置文件或检测报告。")


def status(_args):
    key, source = resolve_key()
    if key:
        print(f"朱雀检测 Key：已绑定（来源：{source}，值已隐藏）")
        print(f"模型：{os.environ.get('MAKERS_MODELS_MODEL', DEFAULT_MODEL)}")
        print(f"接口：{os.environ.get('MAKERS_MODELS_BASE_URL', DEFAULT_BASE_URL).rstrip('/')}")
        return 0
    print(setup_hint())
    return 2


def unbind(_args):
    removed = keychain_unbind()
    if removed:
        print("已删除本机 macOS Keychain 中的朱雀检测 Key。")
    else:
        print("未删除环境变量中的 Key；如需停用，请在当前终端取消 MAKERS_MODELS_KEY。")
    return 0


def iter_files(targets):
    files = []
    for raw in targets:
        path = Path(raw)
        if path.is_file():
            files.append(path)
            continue
        if not path.is_dir():
            raise FileNotFoundError(f"找不到检测目标：{path}")
        for child in sorted(path.rglob("*")):
            if not child.is_file() or child.name in SKIP_NAMES or child.name.endswith(".bak"):
                continue
            if "源程序提取" in child.parts or "说明书章节" in child.parts:
                continue
            if child.suffix.lower() in {".md", ".txt", ".pdf", ".docx"}:
                files.append(child)
            elif child.name == "config.json" and child.parent.name == "auto-fill":
                files.append(child)
    return files


def read_document(path):
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        fields = []
        for section in data.values():
            if isinstance(section, dict):
                for key in ("mainFunction", "devPurpose", "techFeatureText"):
                    value = section.get(key)
                    if isinstance(value, str) and value.strip():
                        fields.append(value.strip())
        return "\n\n".join(fields)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("读取 PDF 需要 pypdf；也可以直接把软件说明书.md 作为检测目标。") from exc
        return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from aigc_rules import split_docx
        return "\n".join(block.text for block in split_docx(path))
    return ""


def normalized_text(text):
    """用于去重的稳定文本表示；不把该表示发送给接口。"""
    return re.sub(r"\s+", " ", text or "").strip()


def text_fingerprint(text):
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def cache_directory():
    configured = os.environ.get("RUANZHU_ZHUSQUE_CACHE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ruanzhu-kit" / "zhusque"
    return Path.home() / ".cache" / "ruanzhu-kit" / "zhusque"


def cache_key(base_url, model, max_chars, text):
    payload = {
        "version": CACHE_VERSION,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "max_chars": max_chars,
        "text": normalized_text(text),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def final_manifest(files, base_url, model, max_chars):
    """生成最终检测指纹；只保存文件名和文本哈希，不保存正文。"""
    rows = []
    for path in files:
        rows.append({"name": path.name, "text": text_fingerprint(read_document(path))})
    payload = {
        "version": CACHE_VERSION,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "max_chars": max_chars,
        "files": sorted(rows, key=lambda row: (row["name"], row["text"])),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def final_marker_path(targets):
    first = Path(targets[0])
    return (first if first.is_dir() else first.parent) / FINAL_MARKER


def load_cached_result(cache_dir, key):
    if cache_dir is None:
        return None
    path = cache_dir / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and "overall_score" in data else None


def save_cached_result(cache_dir, key, result):
    if cache_dir is None:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{key}.json").write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
    except OSError:
        # 缓存不可写不应阻断检测；本次请求结果仍然有效。
        return


def chunks(text, limit=DEFAULT_CHUNK_CHARS):
    text = text.strip()
    if not text:
        return []
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def request_model(key, base_url, model, filename, index, total, text, timeout=90):
    system = (
        "你是软著材料的朱雀风格 AIGC 检测辅助器。只根据输入文本判断文风风险，"
        "不要判断作者身份，不要编造事实，不要把分数解释成作者使用 AI 的概率。"
        "请严格返回 JSON，不要 Markdown 代码围栏。overall_score 为 0-100，越高越像模板化或 AI 文风。"
    )
    user = textwrap.dedent(f"""
        文件：{filename}
        文本块：{index}/{total}

        请输出：
        {{
          "overall_score": 0,
          "level": "低|中|高",
          "human_percent": 0,
          "suspect_percent": 0,
          "ai_percent": 0,
          "summary": "不超过120字",
          "issues": [
            {{"quote": "原文短引（不超过80字）", "reason": "具体文风原因", "rewrite": "保留事实的改写方向"}}
          ]
        }}

        待检测文本：
        {text}
    """).strip()
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": 1800,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"朱雀接口返回 HTTP {exc.code}；Key 未写入报告。") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("朱雀接口连接失败，请检查网络或接口地址。") from exc
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("朱雀接口返回格式无法识别。") from exc
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    return parse_result(str(content))


def parse_result(content):
    candidate = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, flags=re.S | re.I)
    if fenced:
        candidate = fenced.group(1)
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start:end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return {"overall_score": None, "level": "未知", "summary": content[:1000], "issues": []}
    score = data.get("overall_score")
    try:
        data["overall_score"] = max(0, min(100, float(score)))
    except (TypeError, ValueError):
        data["overall_score"] = None
    data.setdefault("level", "未知")
    data.setdefault("summary", "")
    data.setdefault("issues", [])
    return data


def analyse_file(path, key, base_url, model, max_chars, cache_dir=None, text=None):
    text = read_document(path) if text is None else text
    pieces = chunks(text, max_chars)
    if not pieces:
        return {"file": str(path), "chunks": 0, "uploaded": 0, "cached": 0, "score": None, "results": []}
    results = []
    uploaded = 0
    cached = 0
    for i, piece in enumerate(pieces, 1):
        key_for_piece = cache_key(base_url, model, max_chars, piece)
        result = load_cached_result(cache_dir, key_for_piece)
        if result is not None:
            cached += 1
        else:
            result = request_model(key, base_url, model, path.name, i, len(pieces), piece)
            save_cached_result(cache_dir, key_for_piece, result)
            uploaded += 1
        results.append(result)
    scores = [r["overall_score"] for r in results if r.get("overall_score") is not None]
    return {
        "file": str(path),
        "chunks": len(pieces),
        "uploaded": uploaded,
        "cached": cached,
        "score": round(sum(scores) / len(scores), 1) if scores else None,
        "results": results,
    }


def render_report(results, base_url, model):
    lines = [
        "# 朱雀检测辅助报告", "",
        f"> 引擎：{model} ｜ 接口：{base_url}",
        "> 这是联网模型辅助分析，不等同于腾讯官方/商业朱雀检测结论；检测文本已发送到上述接口。",
        "> API Key 只从环境变量或本机 Keychain 读取，本报告不包含 Key；相同文本块会使用本机缓存，不重复请求。", "",
        "## 总览", "", "| 文件 | 文本块 | 平均分 | 结论 |", "| --- | ---: | ---: | --- |",
    ]
    for item in results:
        score = "—" if item["score"] is None else item["score"]
        level = "未返回有效分数" if item["score"] is None else ("高风险" if item["score"] >= 55 else "需抽查" if item["score"] >= 35 else "低风险")
        calls = f"{item.get('uploaded', 0)} 次请求 / {item.get('cached', 0)} 次缓存"
        lines.append(f"| `{item['file']}` | {item['chunks']}（{calls}） | {score} | {level} |")
    for item in results:
        lines += ["", f"## {item['file']}", ""]
        for i, result in enumerate(item["results"], 1):
            lines += [f"### 文本块 {i}", "", f"- 分数：{result.get('overall_score', '—')}", f"- 结论：{result.get('level', '未知')}", f"- 摘要：{result.get('summary', '')}", ""]
            issues = result.get("issues") or []
            if issues:
                lines += ["| 原文短引 | 原因 | 改写方向 |", "| --- | --- | --- |"]
                for issue in issues[:8]:
                    if not isinstance(issue, dict):
                        continue
                    quote = str(issue.get("quote", "")).replace("|", "\\|").replace("\n", " ")
                    reason = str(issue.get("reason", "")).replace("|", "\\|").replace("\n", " ")
                    rewrite = str(issue.get("rewrite", "")).replace("|", "\\|").replace("\n", " ")
                    lines.append(f"| {quote} | {reason} | {rewrite} |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def check(args):
    key, _source = resolve_key()
    if not key:
        print(setup_hint(), file=sys.stderr)
        return 2
    if not args.allow_upload:
        print("朱雀检测会把指定文档文本发送到 EdgeOne Makers 接口。确认后请加 --allow-upload。", file=sys.stderr)
        return 2
    files = iter_files(args.targets)
    if not files:
        print("没有找到可检测的 Markdown、PDF、DOCX 或 auto-fill 配置。", file=sys.stderr)
        return 2
    base_url = os.environ.get("MAKERS_MODELS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("MAKERS_MODELS_MODEL", DEFAULT_MODEL)
    manifest = final_manifest(files, base_url, model, args.max_chars) if args.finalize else None
    marker = final_marker_path(args.targets) if args.finalize else None
    report_path = args.report
    if args.finalize and not report_path:
        report_path = str(final_marker_path(args.targets).with_name("朱雀检测报告.md"))
    if args.finalize and not args.no_cache and marker.exists() and report_path and Path(report_path).exists():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        if previous.get("manifest") == manifest:
            print(f"最终文本未变化，复用已有朱雀检测报告：{report_path}")
            return 0
    cache_dir = None if args.no_cache else cache_directory()
    results = []
    for path in files:
        try:
            results.append(analyse_file(path, key, base_url, model, args.max_chars, cache_dir=cache_dir))
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 1
    report = render_report(results, base_url, model)
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")
        print(f"朱雀检测报告已写入 {report_path}")
    else:
        print(report)
    if args.finalize:
        marker.write_text(json.dumps({
            "version": CACHE_VERSION,
            "manifest": manifest,
            "model": model,
            "base_url": base_url,
            "report": report_path,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已记录本次最终检测指纹：{marker}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="朱雀风格 AIGC 检测辅助（显式联网）")
    sub = parser.add_subparsers(dest="command", required=True)
    bind_parser = sub.add_parser("bind", help="交互式绑定 API Key 到本机 macOS Keychain")
    bind_parser.add_argument("--open", action="store_true", help="绑定前打开腾讯 EdgeOne Makers 页面")
    bind_parser.add_argument("--stdin", action="store_true", help="从标准输入读取 Key，不显示提示")
    sub.add_parser("status", help="查看是否已绑定（不显示 Key）")
    sub.add_parser("unbind", help="删除本机 Keychain 中的绑定")
    def add_check_args(check_parser, finalize=False):
        check_parser.add_argument("targets", nargs="+", help="Markdown/PDF/DOCX/目录")
        check_parser.add_argument("--allow-upload", action="store_true", help="确认允许把文本发送到 EdgeOne Makers")
        check_parser.add_argument("--report", help="报告输出路径")
        check_parser.add_argument("--max-chars", type=int, default=DEFAULT_CHUNK_CHARS, help="每次请求的文本块大小")
        check_parser.add_argument("--no-cache", action="store_true", help="不使用本机结果缓存，强制重新请求")
        check_parser.set_defaults(finalize=finalize)

    check_parser = sub.add_parser("check", help="联网检测指定材料（可多次调用，默认复用缓存）")
    add_check_args(check_parser)
    finalize_parser = sub.add_parser("finalize", help="正文确认后执行一次全量朱雀检测并记录最终指纹")
    add_check_args(finalize_parser, finalize=True)
    args = parser.parse_args()
    try:
        if args.command == "bind":
            return bind(args)
        if args.command == "status":
            return status(args)
        if args.command == "unbind":
            return unbind(args)
        return check(args)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
