"""Incremental Zhuque workflow; transport results remain distinguishable.

Local progress contains locations, hashes and detector results, never credentials.
The original documents are not rewritten by this module.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MIN_WEB_CHARS = 351
TARGET_CHARS = 700
STATE_NAME = ".zhusque-progress.json"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def split_units(text, limit):
    """Keep paragraph/heading boundaries; a change does not shift the whole file.

    Short paragraphs are coalesced with neighbouring context. A tail under the
    web minimum is merged or rebalanced locally, never padded with invented text.
    Offsets are Unicode character offsets in the exact source document.
    """
    if limit < 1:
        raise ValueError("每块字符数必须大于 0。")
    matches = list(re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text.rstrip(), re.S))
    if not matches:
        return []
    spans, start, end = [], None, None
    target = min(TARGET_CHARS, limit)
    for match in matches:
        a, b = match.span()
        is_heading = bool(re.match(r"#{1,2}\s", match.group()))
        if start is not None and (b - start > limit or (is_heading and end - start >= MIN_WEB_CHARS)):
            spans.append((start, end))
            start = end = None
        # Long single paragraphs are bounded, split locally, and cannot shift
        # the boundaries of subsequent paragraphs.
        while b - a > limit:
            cut = a + limit
            if limit >= MIN_WEB_CHARS * 2:
                candidates = list(re.finditer(r"[。！？\n]", text[a + MIN_WEB_CHARS:cut]))
                if candidates:
                    cut = a + MIN_WEB_CHARS + candidates[-1].end()
            spans.append((a, cut))
            a = cut
        if a == b:
            continue
        if start is None:
            start = a
        end = b
        if end - start >= target:
            spans.append((start, end))
            start = end = None
    if start is not None:
        spans.append((start, end))
    return finish_spans(text, spans, limit)


def finish_spans(text, spans, limit):
    if limit >= 800:
        # Keep actual nearby text around isolated headings/short paragraphs so
        # the same unit can be submitted to the website (>350 characters).
        i = 0
        while i < len(spans) and len(spans) > 1:
            a, b = spans[i]
            if len(text[a:b].strip()) >= 400:
                i += 1
                continue
            j = i + 1 if i + 1 < len(spans) else i - 1
            left, right = min(i, j), max(i, j)
            a, b = spans[left][0], spans[right][1]
            if b - a <= limit:
                spans[left:right + 1] = [(a, b)]
                i = max(0, left - 1)
            else:
                cut = a + 400 if i == left else b - 400
                spans[left:right + 1] = [(a, cut), (cut, b)]
                i = right + 1
    units = []
    for a, b in spans:
        raw = text[a:b]
        a += len(raw) - len(raw.lstrip())
        b = a + len(raw.strip())
        if a == b:
            continue
        headings = re.findall(r"^#{1,6}\s+(.+)$", text[:a + 1], re.M)
        own_heading = re.match(r"#{1,6}\s+([^\n]+)", text[a:b])
        units.append({"text": text[a:b], "start": a, "end": b,
                      "line": text.count("\n", 0, a) + 1,
                      "heading": own_heading.group(1) if own_heading else (headings[-1] if headings else "正文")})
    return units


def anchored_units(text, limit, previous):
    """Retain exact old blocks across insertions without storing their text.

    A short prefix hash locates candidate anchors, then the entire block hash
    verifies them. Only uncovered gaps are split again. This prevents a change
    near the beginning from regrouping every later short paragraph.
    """
    lookup = {}
    for row in previous:
        size, prefix, digest = row.get("chars"), row.get("anchor"), row.get("id")
        if (not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= limit
                or not isinstance(prefix, str) or not isinstance(digest, str)):
            continue
        lengths = lookup.setdefault(min(32, size), {}).setdefault(prefix, {})
        lengths.setdefault(size, set()).add(digest)
    matches = []
    for prefix_size, prefixes in lookup.items():
        for start in range(max(0, len(text) - prefix_size + 1)):
            if text[start].isspace():
                continue
            prefix = hashlib.sha256(text[start:start + prefix_size].encode("utf-8")).hexdigest()
            for size, digests in prefixes.get(prefix, {}).items():
                end = start + size
                if end <= len(text) and hashlib.sha256(text[start:end].encode("utf-8")).hexdigest() in digests:
                    matches.append((start, end))
    if not matches:
        return split_units(text, limit)
    spans, cursor = [], 0
    for a, b in sorted(set(matches), key=lambda pair: (pair[0], -pair[1])):
        if a < cursor:
            continue
        spans.extend((cursor + unit["start"], cursor + unit["end"])
                     for unit in split_units(text[cursor:a], limit))
        spans.append((a, b))
        cursor = b
    spans.extend((cursor + unit["start"], cursor + unit["end"])
                 for unit in split_units(text[cursor:], limit))
    return finish_spans(text, spans, limit)


def collect_units(files, max_chars, previous=()):
    import zhusque_check as z
    units, empty_files = [], []
    for path in files:
        text = z.read_document(path)
        old_units = [row for row in previous if isinstance(row, dict) and row.get("file") == str(path)]
        pieces = anchored_units(text, max_chars, old_units)
        # A successful split must account for every non-whitespace character.
        # Otherwise a parser regression could silently certify partial text.
        if "".join(re.sub(r"\s", "", p["text"]) for p in pieces) != re.sub(r"\s", "", text):
            raise ValueError(f"文本分块未覆盖完整正文：{path.name}")
        if not pieces:
            empty_files.append(str(path))
        for index, piece in enumerate(pieces, 1):
            digest = hashlib.sha256(piece["text"].encode("utf-8")).hexdigest()
            units.append({**piece, "id": digest, "file": str(path), "index": index,
                          "anchor": hashlib.sha256(piece["text"][:32].encode("utf-8")).hexdigest(),
                          "chars": len(piece["text"])})
    return units, empty_files


def cached_unit(unit, cache_dir, base_url, model, max_chars, channel):
    import zhusque_check as z
    channels = ("api", "web") if channel == "auto" else (channel,)
    for candidate in channels:
        origin = base_url if candidate == "api" else z.WEB_URL
        key = z.cache_key(origin, model, max_chars, unit["text"])
        result = z.load_cached_result(cache_dir, key)
        if result:
            result["channel"] = candidate
            return result
    return None


class Router:
    """Try each configured transport at most once per unit; no quota-reset loop."""
    def __init__(self, key, channel, base_url, model, material_dir, timeout, force=False, resume_web_units=()):
        self.key, self.channel, self.base_url, self.model = key, channel, base_url, model
        self.material_dir, self.timeout = material_dir, timeout
        self.force = force
        self.browser = None
        self.api_disabled = False
        self.web_disabled = False
        self.events = []
        self.resume_web_units = set(resume_web_units)

    def detect(self, unit):
        import zhusque_check as z
        order = ["api", "web"] if self.channel == "auto" else [self.channel]
        # Computer use may just have completed an already charged webpage
        # submission. Recover it before making any new API request.
        if self.channel == "auto" and unit["id"] in self.resume_web_units:
            order = ["web"]
        failures = []
        for channel in order:
            if channel == "api":
                if not self.key or self.api_disabled:
                    continue
                try:
                    return z.request_model(self.key, self.base_url, self.model,
                                           Path(unit["file"]).name, unit["index"], 1, unit["text"])
                except (OSError, ValueError, RuntimeError) as exc:
                    # Keep keys and server response bodies out of logs.
                    failures.append("api_unavailable")
                    self.api_disabled = True
                    self.events.append({"channel": "api", "reason": "unavailable", "unit": unit["id"]})
                    if self.channel == "auto":
                        print("朱雀 API 未成功返回结果，切换网页检测；本轮不反复重试 API。", flush=True)
            else:
                if self.web_disabled:
                    continue
                if len(unit["text"].strip()) < MIN_WEB_CHARS:
                    failures.append("web_text_too_short")
                    self.events.append({"channel": "web", "reason": "text_too_short", "unit": unit["id"]})
                    continue
                try:
                    from zhusque_browser import BrowserDetector
                    if self.browser is None:
                        self.browser = BrowserDetector(material_dir=self.material_dir, timeout=self.timeout)
                    options = {"force": True} if self.force else {}
                    result = z.parse_result(self.browser.detect(unit["text"], unit["id"], **options))
                    if result.get("evidence", {}).get("text_sha256") != unit["id"]:
                        raise ValueError("网页结果与当前文本不匹配。")
                    result["channel"] = "web"
                    return result
                except (OSError, ValueError, RuntimeError, ImportError) as exc:
                    reason = getattr(exc, "reason", "unavailable")
                    if reason not in ("quota", "captcha", "login", "unavailable", "unsupported"):
                        reason = "unavailable"
                    self.web_disabled = True
                    failures.append("web_" + reason)
                    evidence = getattr(exc, "evidence", {})
                    evidence = evidence if isinstance(evidence, dict) else {}
                    self.events.append({"channel": "web", "reason": reason, "unit": unit["id"],
                                        "evidence": {k: evidence[k] for k in ("page_record", "screenshot", "url", "text_sha256")
                                                     if isinstance(evidence.get(k), str)}})
        error = RuntimeError(" / ".join(failures) or "no_available_channel")
        error.reason = failures[-1] if failures else "no_available_channel"
        raise error

    def close(self):
        if self.browser is not None:
            try:
                self.browser.close()
            except (OSError, RuntimeError):
                # Cleanup failure must not discard successful detection/cache
                # records or the pending computer-use handoff.
                self.events.append({"channel": "web", "reason": "driver_cleanup_failed"})


def totals(rows):
    checked = [row for row in rows if row.get("result")]
    weight = sum(row["chars"] for row in checked)
    ratios = {key: sum(row["chars"] * row["result"]["labels_ratio"][key] for row in checked) / weight
              if weight else 0 for key in ("0", "1", "2")}
    return {"characters": sum(row["chars"] for row in rows), "checked_characters": weight,
            "complete": bool(rows) and len(checked) == len(rows), "ratios": ratios,
            "risk_ratio": ratios["1"] + ratios["2"] if weight else None}


def write_report(path, rows, summary, stats, threshold):
    lines = ["# 朱雀增量检测报告", "",
             "> 首轮覆盖全部检测单元；后续复用相同文本的历史结果，只上传新增或变化单元。",
             "> 汇总按本地检测单元字符数加权，是多次请求的合并结果，不是本轮单次全文检测。",
             "> API 与网页结果分别记录来源；网页按可见分类片段统计时会明确标注。", "",
             f"- 当前覆盖：{summary['checked_characters']:,} / {summary['characters']:,} 字符。",
             f"- 本轮成功上传：{stats['uploaded_units']} 个唯一单元 / {stats['uploaded_characters']:,} 字符；缓存复用：{stats['cached_units']} 个单元；恢复网页结果：{stats.get('resumed_units', 0)} 个。",
             f"- API 返回的本轮 Makers 已知用量合计：{stats['makers_tokens']:,} tokens；{stats.get('unknown_usage_units', 0)} 个成功请求未返回用量（网页不使用 API Token；失败请求是否计费未知）。",
             f"- 项目复核阈值：AI＋疑似 ≤ {threshold:.1%}，这是本项目配置，不是腾讯或登记机构标准。"]
    if summary["checked_characters"]:
        r = summary["ratios"]
        prefix = "全量覆盖合并结果" if summary["complete"] else "已检测部分（不能代表全文）"
        lines.append(f"- {prefix}：人工 {r['0']:.2%}；疑似 {r['2']:.2%}；AI {r['1']:.2%}。")
    if summary.get("empty_files"):
        lines.append("- 无法提取正文，覆盖未完成：" + "、".join(summary["empty_files"]))
    if any(row.get("result", {}).get("channel") == "web" for row in rows if row.get("result")):
        lines.append("- 网页比例按可见分类片段的非空白字符统计，证据见网页证据目录；不冒充 API 原始比例。")
    lines += ["", "| 文件 | 单元/位置 | 字符 | 来源 | 人工 | 疑似 | AI |", "| --- | --- | ---: | --- | ---: | ---: | ---: |"]
    for row in rows:
        result = row.get("result")
        location = f"{row['index']} / L{row['line']}"
        if result:
            r = result["labels_ratio"]
            source = result.get("channel", "api")
            if source == "web" and result.get("evidence", {}).get("source") == "computer_use":
                source += " / computer use"
            source += "（缓存）" if row.get("cached") else "（恢复）" if row.get("resumed") else "（本轮）"
            lines.append(f"| {Path(row['file']).name} | {location} | {row['chars']} | {source} | {r['0']:.2%} | {r['2']:.2%} | {r['1']:.2%} |")
        else:
            lines.append(f"| {Path(row['file']).name} | {location} | {row['chars']} | 待检测 | — | — | — |")
    if stats.get("blocked"):
        lines += ["", "## 待继续", "", f"原因：{stats['blocked']}。已有成功结果已保存，下次运行同一命令继续未完成单元。",
                  "验证码或登录可在已打开的浏览器处理。配额耗尽时等待恢复或配置另一个有额度的正式渠道；无痕窗口不保证恢复额度。"]
    if stats.get("computer_use_handoff"):
        lines += ["", f"Computer Use 交接：{stats['computer_use_handoff']}。状态为待接管，不代表已执行页面操作或已完成检测。"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rewrite_tasks(path, rows):
    lines = ["# 朱雀改写任务单", "",
             "仅列出被朱雀标为 AI / 疑似的文本。标签不能证明作者身份，也不说明具体判定原因。",
             "根据源码、真实界面或操作记录修改；不要编造功能、错误码、配置或实验结果。保留未标记的正文。",
             "只编辑正文主文件；同步对应章节并重新生成 PDF。修改后再次运行 finalize，只检测变更单元。", ""]
    count = 0
    for row in rows:
        result = row.get("result")
        if not result or result["labels_ratio"]["1"] + result["labels_ratio"]["2"] <= 0:
            continue
        count += 1
        lines += [f"## T{count:03d} · {Path(row['file']).name} · {row['heading']}", "",
                  f"- 位置：第 {row['line']} 行起 / 单元 {row['index']} / `{row['id'][:16]}`。",
                  f"- 来源：{result.get('channel', 'api')}；AI {result['labels_ratio']['1']:.2%}，疑似 {result['labels_ratio']['2']:.2%}。"]
        if Path(row["file"]).suffix == ".pdf":
            lines.append("- PDF 位置仅用于复核，请回到同名说明书 Markdown 修改，不能直接编辑 PDF。")
        excerpts = []
        for segment in result.get("segment_labels", []):
            position = segment.get("position")
            if segment.get("label") not in (1, 2) or not isinstance(position, list) or len(position) != 2:
                continue
            start, length = position  # Zhuque positions are [start, length].
            if (isinstance(start, int) and isinstance(length, int) and start >= 0 and length > 0
                    and start + length <= len(row["text"])):
                excerpts.append(row["text"][start:start + length])
        if not excerpts:
            lines.append("- 服务未提供可用的段内位置，以下列出完整检测单元供复核。")
            excerpts = [row["text"]]
        for excerpt in excerpts:
            lines += ["", *("> " + line for line in excerpt.splitlines()), ""]
    if not count:
        lines.append("当前已完成检测的单元中没有 AI / 疑似标签；若仍有待检单元，不能据此认定全文通过。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args):
    import zhusque_check as z
    channel = getattr(args, "channel", "auto")
    plan_only = getattr(args, "plan", False)
    threshold = args.max_risk_ratio
    if not 0 <= threshold <= 1 or not isinstance(args.max_chars, int) or args.max_chars < 1:
        raise ValueError("风险阈值必须在 0～1 之间，每块字符数必须大于 0。")
    if threshold > z.DEFAULT_MAX_RISK_RATIO:
        # 只允许收紧，不允许放宽：放宽后的“通过”不能作为终稿依据
        raise ValueError(f"风险阈值不能高于 {z.DEFAULT_MAX_RISK_RATIO:.0%}；朱雀闸门只允许收紧，不允许放宽。")
    if not plan_only and not args.allow_upload:
        print("检测会把正文发送到朱雀 API 或网页；授权后加 --allow-upload。")
        return 2
    files = z.iter_files(args.targets)
    if not files:
        print("没有找到可检测正文。")
        return 2
    directory = z.material_dir(args.targets[0])
    base_url = z.os.environ.get("MAKERS_MODELS_BASE_URL", z.DEFAULT_BASE_URL).rstrip("/")
    manifest = z.final_manifest(files, base_url, z.DEFAULT_MODEL, args.max_chars)
    previous = []
    try:
        state = json.loads((directory / STATE_NAME).read_text(encoding="utf-8"))
        if isinstance(state, dict) and state.get("version") == z.CACHE_VERSION and state.get("max_chars") == args.max_chars:
            previous = state.get("units", [])
            if not isinstance(previous, list):
                previous = []
    except (OSError, ValueError):
        pass
    units, empty_files = collect_units(files, args.max_chars, previous)
    cache_dir = z.cache_directory()
    rows = []
    for unit in units:
        result = None if args.no_cache else cached_unit(unit, cache_dir, base_url, z.DEFAULT_MODEL, args.max_chars, channel)
        rows.append({**unit, "result": result, "cached": bool(result)})
    pending = {row["id"]: row for row in rows if not row["result"]}
    plan = {"version": z.CACHE_VERSION, "manifest": manifest, "channel": channel,
            "total_units": len(rows), "cached_units": sum(bool(row["result"]) for row in rows),
            "pending_unique_units": len(pending), "pending_characters": sum(row["chars"] for row in pending.values()),
            "empty_files": empty_files,
            "units": [{k: row[k] for k in ("id", "file", "index", "line", "heading", "chars")} for row in pending.values()]}
    handoff = directory / z.HANDOFF_DIR
    atomic_json(handoff / "待检测清单.json", plan)
    print(f"当前 {len(rows)} 个单元；缓存 {plan['cached_units']}；待请求 {len(pending)} 个唯一单元 / {plan['pending_characters']:,} 字符。", flush=True)
    if plan_only:
        print("只生成计划，未联网。")
        return 0

    marker = z.final_marker_path(args.targets)
    # A previous passing marker must never survive a failed forced recheck.
    if marker.exists():
        marker.unlink()
    import zhusque_handoff as cua_handoff
    try:
        active_handoff = cua_handoff.reconcile(directory, rows, manifest)
    except OSError:
        active_handoff = None
        print("旧 Computer Use 交接状态无法更新；本轮仅使用当前文本与有效检测缓存。", flush=True)
    resume_web_units = ([active_handoff["unit_id"]] if active_handoff
                        and active_handoff.get("status") == "pending_computer_use" else [])
    key, _ = z.resolve_key()
    router = Router(key, channel, base_url, z.DEFAULT_MODEL, directory, getattr(args, "browser_timeout", 120),
                    args.no_cache, resume_web_units)
    stats = {"uploaded_units": 0, "uploaded_characters": 0, "cached_units": plan["cached_units"],
             "resumed_units": 0, "makers_tokens": 0, "unknown_usage_units": 0, "api_characters": 0, "blocked": ""}
    fresh = {}
    try:
        for row in rows:
            if row["result"]:
                continue
            if row["id"] in fresh:
                row.update(result=fresh[row["id"]], cached=True)
                stats["cached_units"] += 1
                continue
            try:
                result = router.detect(row)
                result = z.parse_result(result)
            except (OSError, ValueError, RuntimeError, ImportError) as exc:
                stats["blocked"] = getattr(exc, "reason", "invalid_result")
                if stats["blocked"] == "web_text_too_short":
                    continue
                failed_web = next((event for event in reversed(router.events)
                                   if event.get("channel") == "web" and event.get("unit") == row["id"]), None)
                if failed_web:
                    profile_dir = getattr(router.browser, "profile_dir", None)
                    if not isinstance(profile_dir, (str, Path)):
                        profile_dir = None
                    try:
                        record = cua_handoff.create_handoff(directory, row, manifest, args, failed_web["reason"],
                                                            failed_web.get("evidence"), profile_dir)
                        if record and record["status"] == "pending_computer_use":
                            stats["computer_use_handoff"] = str(handoff / cua_handoff.HANDOFF_NAME)
                    except (OSError, ValueError):
                        stats["handoff_error"] = "write_failed"
                        print("Computer Use 交接文件写入失败；成功检测结果仍保留在缓存中。", flush=True)
                break
            actual_channel = result.get("channel", "api")
            origin = base_url if actual_channel == "api" else z.WEB_URL
            z.save_cached_result(cache_dir, z.cache_key(origin, z.DEFAULT_MODEL, args.max_chars, row["text"]), result)
            resumed = actual_channel == "web" and result.get("delivery") == "resumed"
            row.update(result=result, cached=False, resumed=resumed)
            fresh[row["id"]] = result
            if resumed:
                stats["resumed_units"] += 1
            else:
                stats["uploaded_units"] += 1
                stats["uploaded_characters"] += row["chars"]
            if actual_channel == "api":
                stats["makers_tokens"] += result.get("makers_models_usage", {}).get("total_tokens", 0)
                stats["unknown_usage_units"] += "makers_models_usage" not in result
                stats["api_characters"] += result.get("usage", {}).get("total_tokens", 0)
            print(f"已检测 {Path(row['file']).name} / 单元 {row['index']}（{actual_channel}，{row['chars']} 字符）。", flush=True)
    finally:
        router.close()
    # Fill duplicate locations even if a later request was blocked.
    for row in rows:
        if row["result"] is None and row["id"] in fresh:
            row.update(result=fresh[row["id"]], cached=True)
            stats["cached_units"] += 1
    summary = totals(rows)
    summary["empty_files"] = empty_files
    summary["complete"] = summary["complete"] and not empty_files
    current_manifest = z.final_manifest(z.iter_files(args.targets), base_url, z.DEFAULT_MODEL, args.max_chars)
    if current_manifest != manifest:
        summary["complete"] = False
        stats["blocked"] = "source_changed_during_detection"
    try:
        reconciled_handoff = cua_handoff.reconcile(directory, rows, current_manifest)
        if reconciled_handoff and reconciled_handoff.get("status") != "pending_computer_use":
            stats.pop("computer_use_handoff", None)
    except OSError:
        stats["handoff_error"] = "update_failed"
    safe_rows = [{k: v for k, v in row.items() if k != "text"} for row in rows]
    atomic_json(directory / STATE_NAME, {"version": z.CACHE_VERSION, "manifest": manifest, "updated_at": now(),
                                        "base_url": base_url, "model": z.DEFAULT_MODEL, "max_chars": args.max_chars,
                                        "max_risk_ratio": threshold,
                                        "summary": summary, "stats": stats, "events": router.events, "units": safe_rows})
    # A report always reflects the partial state too; incomplete never means passed.
    report_path = Path(args.report) if args.report else directory / "朱雀检测报告.md"
    write_report(report_path, rows, summary, stats, threshold)
    write_rewrite_tasks(directory / "朱雀改写任务单.md", rows)
    print(f"报告：{report_path}；本轮 API Makers 用量 {stats['makers_tokens']:,} tokens。", flush=True)
    if not summary["complete"]:
        print(f"检测未完成：{stats['blocked'] or 'empty_source'}。已保存进度，下次继续；未写入完成标记。")
        return 2
    if args.finalize:
        if summary["risk_ratio"] > threshold:
            print(f"AI＋疑似 {summary['risk_ratio']:.2%}，超过 {threshold:.2%}；请按朱雀改写任务单处理后增量复检。")
            return 1
        atomic_json(marker, {"version": z.CACHE_VERSION, "manifest": manifest, "model": z.DEFAULT_MODEL,
                             "base_url": base_url, "max_chars": args.max_chars, "max_risk_ratio": threshold,
                             "report": str(report_path), "risk_ratio": summary["risk_ratio"],
                             "coverage_complete": True, "channels": sorted({row["result"].get("channel", "api") for row in rows}),
                             "completed_at": now()})
        print("当前文本覆盖完整且通过项目阈值，已更新完成标记。")
    return 0
