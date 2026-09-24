#!/usr/bin/env python3
"""Optional TypeSafe Jev gate for soft-copyright material review.

Jev is used as a typed review signal, not as a replacement for local AIGC,
copyright, or Zhuque checks.  Network access is opt-in and the API key is
read only from TYPESAFE_API_KEY (never from project files).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_MAX_CHARS = 6000
DEFAULT_TIMEOUT = 20
CACHE_VERSION = "jev-material-gate-v1"
CONSOLE_URL = "https://console.typesafe.ai/"


def resolve_key():
    value = os.environ.get("TYPESAFE_API_KEY", "").strip()
    return value or None


def normalize(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_directory():
    configured = os.environ.get("RUANZHU_JEV_CACHE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ruanzhu-kit" / "jev"
    return Path.home() / ".cache" / "ruanzhu-kit" / "jev"


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _compact_excerpt(text, max_chars):
    """Keep headings and a bounded excerpt; do not upload source code."""
    text = re.sub(r"```.*?```", "", text or "", flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[截图]", text)
    text = normalize(text)
    if len(text) <= max_chars:
        return text
    # Preserve the beginning and the end so appendices/FAQ are not silently lost.
    head = max_chars * 2 // 3
    tail = max_chars - head
    return text[:head].rstrip() + " … [正文已截断] … " + text[-tail:].lstrip()


def _local_summary(material_dir):
    summary = {}
    manual = material_dir / "软件说明书.md"
    summary["manual_exists"] = manual.exists()
    summary["manual_excerpt"] = _compact_excerpt(_read_text(manual), DEFAULT_MAX_CHARS)

    for name, key in (("AIGC检测报告.md", "aigc_report"), ("缺失信息清单.md", "todo_report")):
        path = material_dir / name
        if path.exists():
            summary[key] = _compact_excerpt(_read_text(path), 1200)

    shots = material_dir / "截图清单.json"
    if shots.exists():
        try:
            data = json.loads(_read_text(shots))
            items = data.get("items", []) if isinstance(data, dict) else []
            summary["screenshots"] = {
                "count": data.get("count", len(items)) if isinstance(data, dict) else len(items),
                "modules": sorted({str(x.get("module", "")) for x in items if isinstance(x, dict) and x.get("module")}),
            }
        except (json.JSONDecodeError, TypeError):
            summary["screenshots"] = {"count": 0, "invalid_manifest": True}
    else:
        summary["screenshots"] = {"count": 0}

    # Internal reports are useful locally, but their raw text is not uploaded.
    summary["local_report_flags"] = {
        "has_aigc_report": bool(summary.get("aigc_report")),
        "has_todo_report": bool(summary.get("todo_report")),
    }
    return summary


def build_state(material_dir, project=None, max_chars=DEFAULT_MAX_CHARS, local_checks=None,
                include_excerpt=False):
    state = _local_summary(Path(material_dir))
    if include_excerpt:
        state["manual_excerpt"] = _compact_excerpt(state.get("manual_excerpt", ""), max_chars)
    else:
        # TypeSafe's public terms warn against submitting confidential/proprietary
        # information.  The safe default is metrics only; text requires an explicit
        # CLI flag and the user remains responsible for sanitisation.
        for key in ("manual_excerpt", "aigc_report", "todo_report"):
            state.pop(key, None)
    project = project or {}
    state["project"] = {
        "name": project.get("name", Path(material_dir).name),
        "short_name": project.get("short_name", ""),
        "artifact_label": project.get("artifact_label", ""),
        "version": project.get("version", "V1.0"),
        "document_kind": project.get("document_kind", ""),
    }
    if local_checks:
        state["local_checks"] = {
            "metrics": local_checks.get("metrics", {}),
            "aigc": local_checks.get("aigc", {}),
            "issue_counts": local_checks.get("issue_counts", {}),
        }
    return state


def questions():
    # Noul gives a 0..1 yes probability, which maps directly to the conservative
    # thresholds shown in the review UI (0.95 / 0.05).
    return {
        "ui_interaction": {
            "type": "noul",
            "instructions": (
                "Do these software-copyright materials contain enough real, "
                "project-grounded user-interface or interaction evidence for a human "
                "reviewer to verify the described operation?"
            ),
        },
        "engineering_readiness": {
            "type": "noul",
            "instructions": (
                "Do these materials contain enough concrete engineering facts, "
                "operation steps, constraints, and failure handling to be ready for "
                "a human pre-submission review?"
            ),
        },
        "needs_human_review": {
            "type": "noul",
            "instructions": (
                "Should a human review these materials before submission because facts, "
                "screenshots, dates, ownership, or generated wording may still be "
                "incomplete or unverifiable?"
            ),
        },
    }


def _answer_value(answer):
    if not isinstance(answer, dict):
        return None
    value = answer.get("noul")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def gate_result(response, min_ui=0.95, min_engineering=0.95, max_human_review=0.05):
    answers = response.get("answers", {}) if isinstance(response, dict) else {}
    ui = _answer_value(answers.get("ui_interaction"))
    engineering = _answer_value(answers.get("engineering_readiness"))
    human = _answer_value(answers.get("needs_human_review"))
    passed = (ui is not None and engineering is not None and human is not None
              and ui >= min_ui and engineering >= min_engineering and human <= max_human_review)
    return {
        "passed": passed,
        "ui_interaction": ui,
        "engineering_readiness": engineering,
        "human_review": human,
        "thresholds": {
            "ui_interaction_min": min_ui,
            "engineering_readiness_min": min_engineering,
            "human_review_max": max_human_review,
        },
    }


def _request(state, api_key, endpoint=DEFAULT_ENDPOINT, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    payload = {"state": state, "model": model, "questions": questions()}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ruanzhu-kit/jev",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Jev API 返回 HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Jev API 连接失败：{exc.reason}") from exc
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Jev API 返回的不是合法 JSON。") from exc
    if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
        raise RuntimeError("Jev API 返回缺少 answers 字段。")
    return result


def evaluate_material(material_dir, project=None, *, allow_upload=False, max_chars=DEFAULT_MAX_CHARS,
                      endpoint=DEFAULT_ENDPOINT, model=DEFAULT_MODEL, no_cache=False,
                      min_ui=0.95, min_engineering=0.95, max_human_review=0.05,
                      local_checks=None, include_excerpt=False):
    if not allow_upload:
        raise RuntimeError("Jev 会把材料摘要发送到 TypeSafe API；请明确添加 --allow-upload 后再执行。")
    api_key = resolve_key()
    if not api_key:
        raise RuntimeError(f"未设置 TYPESAFE_API_KEY。请先在 {CONSOLE_URL} 获取 API Key。")

    state = build_state(material_dir, project, max_chars=max_chars, local_checks=local_checks,
                        include_excerpt=include_excerpt)
    key = fingerprint({"version": CACHE_VERSION, "endpoint": endpoint, "model": model, "state": state})
    cache = cache_directory()
    cache_file = cache / f"{key}.json"
    response = None
    used_cache = False
    if not no_cache and cache_file.exists():
        try:
            response = json.loads(cache_file.read_text(encoding="utf-8"))
            used_cache = True
        except (OSError, json.JSONDecodeError):
            response = None
    if response is None:
        response = _request(state, api_key, endpoint=endpoint, model=model)
        cache.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "status": "ok",
        "model": response.get("model", model),
        "usage": response.get("usage", {}),
        "cached": used_cache,
        "gate": gate_result(response, min_ui, min_engineering, max_human_review),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="可选 TypeSafe Jev 软著材料闸门（显式联网）")
    parser.add_argument("material_dir", help="包含 软件说明书.md 的材料目录")
    parser.add_argument("--project-json", help="项目配置 JSON；只读取名称、简称、端类型等非源码字段")
    parser.add_argument("--allow-upload", action="store_true", help="确认允许发送材料摘要到 TypeSafe API")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--include-excerpt", action="store_true",
                        help="额外发送截断后的说明书摘要；仅限已确认可外传的非机密内容")
    parser.add_argument("--endpoint", default=os.environ.get("TYPESAFE_API_URL", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default=os.environ.get("TYPESAFE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--report", help="写入 Jev 闸门 JSON 报告")
    args = parser.parse_args()
    project = {}
    if args.project_json:
        project = json.loads(Path(args.project_json).read_text(encoding="utf-8"))
    try:
        result = evaluate_material(Path(args.material_dir), project, allow_upload=args.allow_upload,
                                    max_chars=max(100, args.max_chars), endpoint=args.endpoint,
                                    model=args.model, no_cache=args.no_cache,
                                    include_excerpt=args.include_excerpt)
    except RuntimeError as exc:
        print(f"Jev 检查未执行：{exc}", file=sys.stderr)
        return 2
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
