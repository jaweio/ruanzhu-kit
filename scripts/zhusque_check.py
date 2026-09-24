#!/usr/bin/env python3
"""腾讯朱雀文本检测及本地交接。密钥只从本机环境/钥匙串读取。"""

import argparse
import hashlib
import getpass
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from datetime import datetime, timezone

# API key 管理页和不需要 API key 的人工检测页分开：前者用于自动检测，
# 后者是没有配置 Key 时的可点击回退入口。
CONSOLE_URL = "https://console.cloud.tencent.com/edgeone/makers?tab=models&subTab=apikey"
WEB_URL = "https://matrix.tencent.com/ai-detect/"
DEFAULT_BASE_URL = "https://ai-gateway.edgeone.link/v1"
DEFAULT_MODEL = "@makers/zhuque-text"
KEYCHAIN_SERVICE = "ruanzhu-kit.zhusque"
KEYCHAIN_ACCOUNT = "MAKERS_MODELS_KEY"
ENV_NAMES = ("MAKERS_MODELS_KEY", "RUANZHU_ZHUSQUE_API_KEY")
DEFAULT_CHUNK_CHARS = 12000
CACHE_VERSION = "zhuque-classify-v2"
FINAL_MARKER = ".zhusque-final.json"
# 朱雀检测是终稿必过闸门；只有用户在对话/界面中明确拒绝上传，且累计拒绝次数达到阈值，
# 才记为“用户豁免”。豁免不等于已检测，清单和看板会如实标注。
DECLINE_MARKER = ".zhusque-declined.json"
DECLINE_THRESHOLD = 2
HANDOFF_DIR = "朱雀复核"
DEFAULT_MAX_RISK_RATIO = 0.20
def setup_hint():
    return (
        "未绑定朱雀检测 Key。请先在腾讯 EdgeOne Makers 控制台生成 API Key：\n"
        f"{CONSOLE_URL}\n\n"
        "如果暂时不配置 Key，可直接打开腾讯朱雀网页，把生成的说明书或正文上传检测：\n"
        f"{WEB_URL}\n\n"
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


def status_payload():
    key, source = resolve_key()
    return {
        "configured": bool(key),
        "source": source or "",
        "model": DEFAULT_MODEL,
        "base_url": os.environ.get("MAKERS_MODELS_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "console_url": CONSOLE_URL,
        "web_url": WEB_URL,
    }


def status(args):
    payload = status_payload()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["configured"] else 2
    if payload["configured"]:
        print(f"朱雀检测 Key：已绑定（来源：{payload['source']}，值已隐藏）")
        print(f"模型：{payload['model']}")
        print(f"接口：{payload['base_url']}")
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
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from artifact_manifest import formal_material_paths
    files = []
    for raw in targets:
        path = Path(raw)
        if path.is_file():
            files.append(path)
            continue
        if not path.is_dir():
            raise FileNotFoundError(f"找不到检测目标：{path}")
        formal = formal_material_paths(path)
        # 白名单取材，绝不递归扫描历史、源码、声明和内部报告。
        candidates = [path / "软件说明书.md", path / "申请表填报文案.md", path / "auto-fill" / "config.json"]
        if formal.get("docPdf"):
            candidates.append(formal["docPdf"])
        else:
            for directory in (path / "提交材料", path):
                candidates.extend(sorted(directory.glob("*软件说明*.pdf")))
        files.extend(p for p in candidates if p.is_file())
    return list(dict.fromkeys(files))


def read_document(path):
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        fields = []
        for section in data.values():
            if isinstance(section, dict):
                for key in ("mainFunction", "devPurpose", "targetIndustry", "techFeatureText"):
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
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


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
    try:
        return parse_result(data)
    except (ValueError, TypeError):
        return None


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
    if limit < 1:
        raise ValueError("每块字符数必须大于 0。")
    text = text.strip()
    if not text:
        return []
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def request_model(key, base_url, model, filename, index, total, text, timeout=60):
    # 正式 classify API；Chat Completions 的文风意见不能当朱雀结论。
    if model != DEFAULT_MODEL:
        raise ValueError("朱雀检测只支持 @makers/zhuque-text，不能用聊天模型替代。")
    if not base_url.startswith("https://"):
        raise ValueError("朱雀接口必须使用 HTTPS。")
    payload = json.dumps({"text": text, "is_merge": False}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/providers/zhuque-text/classify",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"朱雀接口返回 HTTP {exc.code}；Key 未写入报告。") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("朱雀接口连接失败，请检查网络或接口地址。") from exc
    return parse_result(result)


def parse_result(content):
    """严格校验朱雀返回值；错误、空结果、聊天模型结果不能标成已检测。"""
    try:
        data = json.loads(content) if isinstance(content, str) else content
        if not isinstance(data, dict) or data.get("status") != "success":
            raise ValueError()
        ratios = data["labels_ratio"]
        values = [ratios[k] for k in ("0", "1", "2")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError()
        if abs(sum(values) - 1) > 0.02:
            raise ValueError()
        # 缓存只保存数值与位置，不保存服务返回的原文或摘要。
        segments = [{k: s[k] for k in ("label", "conf", "order", "position") if k in s}
                    for s in data.get("segment_labels", []) if isinstance(s, dict)]
        return {"status": "success", "labels_ratio": dict(zip(("0", "1", "2"), values)),
                "segment_labels": segments, "overall_score": round((values[1] + values[2]) * 100, 4)}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("朱雀未返回有效检测结果；本次未通过，不生成完成标记。") from exc


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
    ratios = {str(k): sum(r["labels_ratio"][str(k)] for r in results) / len(results)
              for k in (0, 1, 2)}
    return {
        "file": str(path),
        "chunks": len(pieces),
        "uploaded": uploaded,
        "cached": cached,
        "score": round(sum(scores) / len(scores), 1) if scores else None,
        "ratios": ratios,
        "risk_ratio": ratios["1"] + ratios["2"],
        "results": results,
    }


def render_report(results, base_url, model):
    lines = [
        "# 朱雀检测报告", "",
        f"> 引擎：{model} ｜ 接口：{base_url}/providers/zhuque-text/classify",
        "> 本报告由腾讯朱雀 zhuque-text 正式检测接口返回；比例是检测结果，不是作者使用 AI 的概率。",
        "> API Key 只从环境变量或本机 Keychain 读取，本报告不包含 Key；相同文本块会使用本机缓存，不重复请求。", "",
        "## 总览", "", "| 文件 | 文本块 | AI | 疑似 AI | 人工 | 状态 |", "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        ratios = item.get("ratios") or {"0": 0, "1": 0, "2": 0}
        state = "通过" if item.get("risk_ratio", 1) <= DEFAULT_MAX_RISK_RATIO else "需改写后复测"
        calls = f"{item.get('uploaded', 0)} 次请求 / {item.get('cached', 0)} 次缓存"
        lines.append(f"| `{item['file']}` | {item['chunks']}（{calls}） | {ratios['1']:.1%} | {ratios['2']:.1%} | {ratios['0']:.1%} | {state} |")
    for item in results:
        lines += ["", f"## {item['file']}", ""]
        for i, result in enumerate(item["results"], 1):
            ratios = result["labels_ratio"]
            lines += [f"### 文本块 {i}", "", f"- AI：{ratios['1']:.2%}", f"- 疑似 AI：{ratios['2']:.2%}", f"- 人工：{ratios['0']:.2%}", ""]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_web_handoff(target):
    """Key 不可用时落盘网页检测入口，便于用户点开后自行上传。"""
    directory = Path(target) if Path(target).is_dir() else Path(target).parent
    handoff = directory / HANDOFF_DIR
    handoff.mkdir(parents=True, exist_ok=True)
    (handoff / "网页检测说明.md").write_text(
        "# 朱雀网页检测\n\n"
        "当前未配置朱雀 API Key，材料未上传。请打开腾讯朱雀网页，手动上传最终软件说明书 PDF 或正文：\n\n"
        f"{WEB_URL}\n\n"
        "若需要自动检测，请在 EdgeOne Makers 控制台生成 Key 后，在软著工具箱设置中配置，或运行 `zhusque_check.py bind`。\n",
        encoding="utf-8",
    )
    return handoff


def material_dir(target):
    target = Path(target)
    return target if target.is_dir() else target.parent


def load_declines(project_dir):
    path = Path(project_dir) / DECLINE_MARKER
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = data.get("declines", []) if isinstance(data, dict) else []
    return [r for r in records if isinstance(r, dict) and str(r.get("reason", "")).strip()]


def decline_status(project_dir):
    records = load_declines(project_dir)
    return {
        "count": len(records),
        "threshold": DECLINE_THRESHOLD,
        "waived": len(records) >= DECLINE_THRESHOLD,
        "marker": str(Path(project_dir) / DECLINE_MARKER),
    }


def decline(args):
    """记录一次用户明确拒绝上传朱雀检测。只能在用户本人明确表示拒绝后调用。"""
    if not args.user_declined:
        print("只有用户本人明确拒绝朱雀检测后才能记录；确认后请加 --user-declined。", file=sys.stderr)
        return 2
    reason = (args.reason or "").strip()
    if not reason:
        print("请用 --reason 记录用户拒绝的原话或理由。", file=sys.stderr)
        return 2
    directory = material_dir(args.target)
    if not directory.is_dir():
        print(f"材料目录不存在：{directory}", file=sys.stderr)
        return 2
    records = load_declines(directory)
    records.append({"reason": reason, "source": args.source,
                    "declined_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    (directory / DECLINE_MARKER).write_text(json.dumps({"declines": records}, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    state = decline_status(directory)
    if state["waived"]:
        print(f"用户已明确拒绝朱雀检测 {state['count']} 次，本材料记为“用户豁免”（未检测），闸门放行。")
    else:
        print(f"已记录用户拒绝（{state['count']}/{DECLINE_THRESHOLD}）。朱雀检测仍是必需步骤；"
              "请向用户说明未检测的风险并再次确认，用户再次明确拒绝才会豁免。")
    return 0


def check(args):
    key, _source = resolve_key()
    if not key:
        write_web_handoff(args.targets[0])
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
    model = DEFAULT_MODEL
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
        if not results or any(item.get("score") is None for item in results):
            print("朱雀未返回完整结果，本次不生成最终完成标记。", file=sys.stderr)
            return 1
        risk = sum(item.get("risk_ratio", 1) for item in results) / len(results)
        if risk > args.max_risk_ratio:
            print(f"朱雀检测未通过：AI+疑似占比 {risk:.2%}，超过 {args.max_risk_ratio:.2%}。请按报告改写后重测。", file=sys.stderr)
            return 1
        marker.write_text(json.dumps({
            "version": CACHE_VERSION,
            "manifest": manifest,
            "model": model,
            "base_url": base_url,
            "report": report_path,
            "risk_ratio": risk,
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已记录本次最终检测指纹：{marker}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="朱雀风格 AIGC 检测辅助（显式联网）")
    sub = parser.add_subparsers(dest="command", required=True)
    bind_parser = sub.add_parser("bind", help="交互式绑定 API Key 到本机 macOS Keychain")
    bind_parser.add_argument("--open", action="store_true", help="绑定前打开腾讯 EdgeOne Makers 页面")
    bind_parser.add_argument("--stdin", action="store_true", help="从标准输入读取 Key，不显示提示")
    status_parser = sub.add_parser("status", help="查看是否已绑定（不显示 Key）")
    status_parser.add_argument("--json", action="store_true", help="输出不含密钥的机器可读状态")
    sub.add_parser("unbind", help="删除本机 Keychain 中的绑定")
    decline_parser = sub.add_parser("decline", help=f"记录一次用户明确拒绝朱雀检测（累计 {DECLINE_THRESHOLD} 次才豁免）")
    decline_parser.add_argument("target", help="材料目录")
    decline_parser.add_argument("--reason", required=True, help="用户拒绝的原话或理由")
    decline_parser.add_argument("--source", default="cli", help="记录来源，如 chat / app")
    decline_parser.add_argument("--user-declined", action="store_true", help="确认这是用户本人的明确拒绝")
    def add_check_args(check_parser, finalize=False):
        check_parser.add_argument("targets", nargs="+", help="Markdown/PDF/DOCX/目录")
        check_parser.add_argument("--allow-upload", action="store_true", help="确认允许把文本发送到 EdgeOne Makers")
        check_parser.add_argument("--report", help="报告输出路径")
        check_parser.add_argument("--max-chars", type=int, default=DEFAULT_CHUNK_CHARS, help="每次请求的文本块大小")
        check_parser.add_argument("--no-cache", action="store_true", help="不使用本机结果缓存，强制重新请求")
        check_parser.add_argument("--max-risk-ratio", type=float, default=DEFAULT_MAX_RISK_RATIO,
                                  help="AI+疑似占比闸门，默认 0.20；仅 finalize 生效")
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
        if args.command == "decline":
            return decline(args)
        return check(args)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
