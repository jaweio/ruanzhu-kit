"""A local, inspectable handoff contract for a host computer-use agent.

This module does not operate a browser or accept hand-entered detector scores.
The host must perform real UI work; the normal detector verifies the result.
"""
import hashlib
import json
import os
import re
import sys
import uuid
import argparse
from datetime import datetime, timezone
from pathlib import Path

WEB_URL = "https://matrix.tencent.com/ai-detect/"
HANDOFF_NAME = "computer-use-handoff.json"
EVENT_PREFIX = "RUANZHU_COMPUTER_USE_HANDOFF "
ELIGIBLE_REASONS = {"captcha", "login", "unavailable", "unsupported", "selector", "connection"}


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def private_write(path, text):
    """Atomic owner-only files, including the exact pending source text."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_json(path, data):
    private_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_active(directory):
    try:
        value = json.loads((Path(directory) / "朱雀复核" / HANDOFF_NAME).read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("version") != 1
                or not re.fullmatch(r"[a-f0-9]{32}", str(value.get("handoff_id", "")))
                or not isinstance(value.get("source"), dict)
                or not all(isinstance(value.get(key), str) for key in
                           ("status", "reason", "unit_id", "text_sha256", "text_path", "profile_dir"))
                or not all(key in value["source"] for key in ("file", "line"))
                or not isinstance(value["source"]["file"], str) or not value["source"]["file"]):
            return None
        return value
    except (OSError, ValueError):
        return None


def resume_argv(args):
    """Use argv, never a shell command. Resume must not force duplicate requests."""
    command = [sys.executable, str(Path(__file__).with_name("zhusque_check.py").resolve()),
               "finalize" if args.finalize else "check", *(str(Path(p).resolve()) for p in args.targets),
               "--allow-upload", "--channel", getattr(args, "channel", "auto"),
               "--max-chars", str(args.max_chars), "--max-risk-ratio", str(args.max_risk_ratio),
               "--browser-timeout", str(getattr(args, "browser_timeout", 120))]
    if args.report:
        command.extend(["--report", str(Path(args.report).resolve())])
    return command


def receipt_reference(directory, unit, profile_dir):
    """Reference only a driver receipt whose full identity matches this unit."""
    identity = {"request_id": unit["id"], "text_sha256": unit["id"],
                "profile_dir": str(Path(profile_dir).resolve()), "url": WEB_URL}
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    path = Path(directory) / "朱雀复核" / "网页证据" / f"pending-{digest}.json"
    result = {"path": str(path.resolve()), "exists": False, "identity_matches": False,
              "phase": None, "submission_may_have_occurred": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        result["exists"] = True
        if isinstance(value, dict) and all(value.get(k) == v for k, v in identity.items()):
            phase = value.get("phase")
            result.update(identity_matches=True, phase=phase if phase in {"submitted", "click_pending", "uncertain"} else None,
                          submission_may_have_occurred=True)
    except (OSError, ValueError):
        pass
    return result


def _persist(directory, record):
    base = Path(directory) / "朱雀复核"
    save_json(base / "接管记录" / (record["handoff_id"] + ".json"), record)
    save_json(base / HANDOFF_NAME, record)
    pending = record["status"] == "pending_computer_use"
    lines = ["# 朱雀 Computer Use 接管", "", f"- 状态：{record['status']}。",
             f"- 原因：{record['reason']}。", f"- 当前单元：`{record['unit_id']}`。",
             f"- 原文：{record['text_path']}；UTF-8 SHA-256 必须与当前单元一致。",
             f"- 来源：{record['source']['file']}，第 {record['source']['line']} 行起。",
             f"- 官方页面：{WEB_URL}", f"- 专用浏览器目录：{record['profile_dir']}", ""]
    if pending:
        lines += ["本记录是 ruanzhu-kit Skill 内部状态，由当前 agent 在同一任务中读取并继续；有可用工具时，不要求用户复制任务、另开会话或安装独立软件。",
                  "当前 agent 应使用实际 Computer Use 工具优先接管已有窗口，先查看实时页面与提交凭据，再处理页面点击。",
                  "出现验证码或登录时，agent 不得代为完成：停下并请用户本人在已打开窗口完成，用户告知完成后再续检。",
                  "原窗口无法接管时，可在其他受控浏览器打开同一官方页面，但只可提交已确认尚未提交的单元；不得将已提交或状态不明的单元迁移重发。",
                  "若已有提交或提交状态不确定，先核对当前结果，不能直接再次点击检测；不得删除提交凭据来强行重发。",
                  "仅在确认尚未提交当前原文后提交一次。页面操作成功不等于检测成功，随后执行 JSON 中的 resume_argv 继续正常验证。",
                  "只能接受完整匹配当前原文的真实分类结果；不得手填截图分数、伪造检测结果或绕过额度限制。",
                  "Python 脚本只生成交接记录，无法自行调用宿主的 Computer Use 工具。"]
    elif record["status"] == "blocked_quota":
        lines += ["当前是服务额度限制；Computer Use 不会产生新额度。保留进度，等待额度恢复或使用有额度的正式 API 渠道。"]
    else:
        lines += ["本记录已结束，不能继续作为待操作指令；历史证据保留在接管记录目录。"]
    private_write(base / "Computer-Use接管说明.md", "\n".join(lines) + "\n")


def create_handoff(directory, unit, manifest, args, reason, evidence=None, profile_dir=None):
    """Persist a pending action, not an assertion that computer use was run."""
    reason = reason.removeprefix("web_")
    if reason not in ELIGIBLE_REASONS | {"quota"}:
        return None
    digest = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
    if digest != unit["id"]:
        raise ValueError("待交接文本与检测单元 SHA-256 不一致。")
    if profile_dir is None:
        from zhusque_browser import default_profile_dir
        profile_dir = default_profile_dir()
    profile_dir = str(Path(profile_dir).resolve())
    import zhusque_check as z
    directory = Path(directory).resolve()
    base = directory / "朱雀复核"
    text_path = base / "待检文本" / (digest + ".txt")
    private_write(text_path, unit["text"])
    evidence = evidence if isinstance(evidence, dict) else {}
    safe_evidence = {key: evidence[key] for key in ("page_record", "screenshot", "text_sha256", "request_id")
                     if isinstance(evidence.get(key), str)}
    receipt = receipt_reference(directory, unit, profile_dir)
    status = "blocked_quota" if reason == "quota" else "pending_computer_use"
    record = {"version": 1, "type": "zhusque_computer_use_handoff", "handoff_id": uuid.uuid4().hex,
              "status": status, "reason": reason, "created_at": timestamp(), "updated_at": timestamp(),
              "manifest": manifest, "material_dir": str(directory), "unit_id": digest,
              "request_id": digest, "text_sha256": digest, "text_path": str(text_path),
              "text_encoding": "utf-8", "text_characters": len(unit["text"]),
              "source": {**{key: unit[key] for key in ("index", "line", "heading", "start", "end")},
                         "file": str(Path(unit["file"]).resolve())},
              "url": WEB_URL, "profile_dir": profile_dir, "evidence": safe_evidence,
              "pending_receipt": receipt, "resume_argv": resume_argv(args),
              "detection": {"targets": [str(Path(target).resolve()) for target in args.targets],
                            "base_url": os.environ.get("MAKERS_MODELS_BASE_URL", z.DEFAULT_BASE_URL).rstrip("/"),
                            "model": z.DEFAULT_MODEL, "max_chars": args.max_chars},
              "resume_policy": "retain-successful-cache-and-pending-submission",
              "actions": {"allowed": (["inspect_live_page", "click_visible_controls",
                                         "complete_authorized_login", "resume_matching_submission"]
                                        if status == "pending_computer_use" else []),
                          "requires_verified_not_submitted": (["submit_current_text_once"]
                                                               if status == "pending_computer_use" else []),
                          "forbidden": ["duplicate_uncertain_submission", "fabricate_result", "import_screenshot_score",
                                        "reset_quota_by_new_identity", "erase_submission_receipt",
                                        "solve_captcha"]},
              "completion": "Only validated full-text classifications from the normal detector or a live computer-use capture may enter cache; screenshots or total scores alone are insufficient."}
    previous = load_active(directory)
    if previous and previous.get("status") == "pending_computer_use":
        previous.update(status="superseded", updated_at=timestamp(), superseded_by=record["handoff_id"])
        _persist(directory, previous)
    _persist(directory, record)
    if status == "pending_computer_use":
        event = {key: record[key] for key in ("version", "type", "status", "reason", "unit_id", "request_id",
                                            "text_path", "url", "profile_dir", "resume_argv")}
        event["handoff_path"] = str(base / HANDOFF_NAME)
        print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
    return record


def reconcile(directory, rows, manifest):
    """Mark old pending work stale/resolved; never turn a handoff into a result."""
    record = load_active(directory)
    if not record or record.get("status") not in {"pending_computer_use", "blocked_quota"}:
        return record
    source_path = Path(record["source"]["file"]).resolve()
    matching = [row for row in rows if row["id"] == record.get("unit_id")
                and Path(row["file"]).resolve() == source_path]
    exact = matching and all(hashlib.sha256(row["text"].encode()).hexdigest() == record.get("text_sha256") for row in matching)
    if record.get("manifest") != manifest or not exact:
        record.update(status="stale", updated_at=timestamp(), resolution_reason="source_changed")
    else:
        completed = next((row for row in matching if row.get("result")), None)
        if not completed:
            return record
        result = completed["result"]
        from zhusque_check import parse_result
        try:
            result = parse_result(result)
        except (ValueError, TypeError):
            return record
        if result.get("channel") == "web" and result.get("evidence", {}).get("text_sha256") != record["text_sha256"]:
            return record
        record.update(status="resolved", updated_at=timestamp(), resolved_at=timestamp(),
                      resolution={"channel": result.get("channel", "api"), "from_cache": bool(completed.get("cached")),
                                  "text_sha256": record["text_sha256"], "evidence": result.get("evidence", {})})
    _persist(directory, record)
    return record


def import_cua_result(directory, capture_path):
    """Validate a trusted host's live DOM capture; never accept a supplied score.

    Evidence provenance relies on the host actually using computer-use tools.
    This validates the submitted text, current materials, full classification
    coverage, timestamp and evidence files; it cannot attest browser actions.
    """
    import zhusque_check as z
    directory = Path(directory).resolve()
    record = load_active(directory)
    if not record or record.get("status") != "pending_computer_use":
        raise ValueError("没有当前待 Computer Use 接管的单元，不能导入结果。")
    config = record.get("detection")
    if not isinstance(config, dict) or not all(key in config for key in ("targets", "base_url", "model", "max_chars")):
        raise ValueError("交接记录缺少检测配置，请重新生成交接。")
    if (not isinstance(config["targets"], list) or not config["targets"]
            or not all(isinstance(target, str) for target in config["targets"])
            or not isinstance(config["max_chars"], int) or isinstance(config["max_chars"], bool)
            or config["max_chars"] < 1 or not all(isinstance(config[k], str) for k in ("base_url", "model"))):
        raise ValueError("交接记录检测配置无效。")
    current_manifest = z.final_manifest(z.iter_files(config["targets"]), config["base_url"], config["model"], config["max_chars"])
    if current_manifest != record.get("manifest"):
        record.update(status="stale", resolution_reason="source_changed", updated_at=timestamp())
        _persist(directory, record)
        raise ValueError("材料已变更，旧 Computer Use 结果不能复用。")
    text_path = Path(record["text_path"]).resolve()
    if text_path.parent != (directory / "朱雀复核" / "待检文本").resolve():
        raise ValueError("待检原文路径不属于当前材料交接目录。")
    text = text_path.read_bytes().decode("utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest != record["text_sha256"] or digest != record["unit_id"]:
        raise ValueError("待检原文 SHA-256 校验失败。")
    source = Path(record["source"]["file"])
    if text not in z.read_document(source):
        raise ValueError("当前源文件已不包含该完整待检原文。")
    capture = json.loads(Path(capture_path).read_text(encoding="utf-8"))
    if not isinstance(capture, dict) or capture.get("source") != "computer_use_live_dom":
        raise ValueError("必须提供宿主 Computer Use 实时读取的页面分类片段。")
    if (not isinstance(capture.get("url"), str) or capture["url"].rstrip("/") != WEB_URL.rstrip("/")
            or capture.get("submitted_text_sha256") != digest or capture.get("request_id") != record["request_id"]):
        raise ValueError("Computer Use 页面来源或提交文本标识不匹配。")
    try:
        captured = datetime.fromisoformat(capture["captured_at"].replace("Z", "+00:00"))
        created = datetime.fromisoformat(record["created_at"])
        current = datetime.now(timezone.utc)
        if (captured.tzinfo is None or (captured - created).total_seconds() < -60
                or (captured - current).total_seconds() > 300 or (current - captured).total_seconds() > 86400):
            raise ValueError()
    except (KeyError, AttributeError, TypeError, ValueError):
        raise ValueError("页面证据时间无效或早于本次交接。") from None
    evidence = capture.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    evidence_paths = {}
    for field in ("screenshot", "page_record", "accessibility_record"):
        value = evidence.get(field)
        if (isinstance(value, str) and Path(value).is_absolute() and Path(value).is_file()
                and Path(value).stat().st_size > 0):
            evidence_paths[field] = str(Path(value).resolve())
    if not evidence_paths:
        raise ValueError("缺少实际页面截图、DOM 或无障碍树证据文件。")
    segments = capture.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("缺少完整分类正文；不接受仅截图占比或总分。")
    normalized_segments = []
    for segment in segments:
        if (not isinstance(segment, dict) or not isinstance(segment.get("text"), str)
                or not isinstance(segment.get("label"), int) or isinstance(segment.get("label"), bool)
                or segment.get("label") not in (0, 1, 2)):
            raise ValueError("页面分类片段或标签无效。")
        normalized_segments.append({"text": segment["text"], "label": segment["label"]})
    original_positions = [index for index, char in enumerate(text) if not char.isspace()]
    original = "".join(text[index] for index in original_positions)
    observed = "".join(re.sub(r"\s", "", segment["text"]) for segment in normalized_segments)
    if not original or observed != original:
        raise ValueError("页面分类正文未完整匹配待检原文，不能计为检测完成。")
    counts = {"0": 0, "1": 0, "2": 0}
    classified, cursor = [], 0
    for segment in normalized_segments:
        length = len(re.sub(r"\s", "", segment["text"]))
        if not length:
            continue
        start, end = original_positions[cursor], original_positions[cursor + length - 1] + 1
        classified.append({"label": segment["label"], "position": [start, end - start], "order": len(classified)})
        counts[str(segment["label"])] += length
        cursor += length
    archive_path = directory / "朱雀复核" / "网页证据" / (record["handoff_id"] + "-computer-use.json")
    archive = {"source": "computer_use_live_dom", "url": WEB_URL, "request_id": record["request_id"],
               "submitted_text_sha256": digest, "captured_at": capture["captured_at"],
               "segments": normalized_segments, "evidence": evidence_paths, "handoff_id": record["handoff_id"]}
    save_json(archive_path, archive)
    result_evidence = {"page_record": str(archive_path), "url": WEB_URL, "text_sha256": digest,
                       "request_id": record["request_id"], "captured_at": capture["captured_at"],
                       "source": "computer_use", "ratio_source": "visible-segment-nonwhitespace-character-weighted"}
    if "screenshot" in evidence_paths:
        result_evidence["screenshot"] = evidence_paths["screenshot"]
    result = z.parse_result({"status": "success", "channel": "web", "delivery": "resumed",
                             "labels_ratio": {key: count / len(original) for key, count in counts.items()},
                             "segment_labels": classified, "evidence": result_evidence})
    cache_dir = z.cache_directory()
    cache_key = z.cache_key(z.WEB_URL, config["model"], config["max_chars"], text)
    z.save_cached_result(cache_dir, cache_key, result)
    # The shared cache writer is deliberately best-effort for live requests,
    # but this import relies on durable cache storage for the next finalize.
    # Do not claim resolution if a failed write was silently ignored.
    if z.load_cached_result(cache_dir, cache_key) != result:
        raise OSError("Computer Use 检测结果未完整写入缓存；交接仍待处理，请修复缓存目录后重新导入。")
    # Cached result is available, but only normal finalize can certify all files.
    record.update(status="resolved", updated_at=timestamp(), resolved_at=timestamp(),
                  resolution={"channel": "web", "source": "computer_use", "text_sha256": digest,
                              "evidence": result_evidence, "finalize_required": True})
    _persist(directory, record)
    return {"status": "result_cached", "unit_id": digest, "channel": "web", "source": "computer_use",
            "resume_argv": record["resume_argv"], "evidence": str(archive_path), "finalize_required": True}


def main():
    parser = argparse.ArgumentParser(description="朱雀 Computer Use 交接与完整分类结果校验")
    sub = parser.add_subparsers(dest="command", required=True)
    import_parser = sub.add_parser("import-cua-result", help="校验宿主从真实页面读取的完整分类结果后写入缓存")
    import_parser.add_argument("material_dir")
    import_parser.add_argument("capture_json")
    args = parser.parse_args()
    try:
        result = import_cua_result(args.material_dir, args.capture_json)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
