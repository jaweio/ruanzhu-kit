#!/usr/bin/env python3
"""软著材料 AIGC 文风检测（本地、离线、无第三方依赖）。

对说明书 / 申请表文案 / auto-fill 配置逐块打分（0-100，越高越像模板化 AI 文），
按章节汇总，列出高风险段落及原因，供 aigc_rewrite.py 和人工改写使用。

注意：这是按 references/writing-style.md 规则做的启发式估计，
与任何商业 AIGC 检测服务的结果不是一回事，只用来定位该改哪里。

用法：
  python3 aigc_check.py soft-copyright-materials/01-XXX软件
  python3 aigc_check.py 软件说明书.md --report AIGC检测报告.md --json out.json
  python3 aigc_check.py <目录> --fail-above 40      # 超阈值退出码 1，可用作提交前闸门
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aigc_rules import (ABSTRACT_NOUNS, BOLD_LEAD, CONDITION, FAQ_Q, EXPERIENCE, OPERATION_VERBS, PAREN, PLACEHOLDER,  # noqa: E402
                        TEMPLATE_OPENERS, blacklist_hits, cv, fact_hits, item_shape, load_blocks,
                        common_term_hits, common_term_warnings, marketing_hits, sentences)
from artifact_manifest import formal_material_paths  # noqa: E402

ENUM = re.compile(r"(?:[\u4e00-\u9fa5]{2,6}、){4,}[\u4e00-\u9fa5]{2,6}")


def is_operation(sentence):
    return bool(re.search(OPERATION_VERBS, sentence) or re.search(CONDITION, sentence))

LOW, HIGH = 35, 55
SKIP_NAMES = {"源码材料清单.md", "截图证据计划.md", "AIGC检测报告.md", "AIGC检测报告-当前复核.md",
              "AIGC改写任务单.md", "源程序提取报告.md", "缺失信息清单.md", "待补充信息清单.md", "材料上传清单.json"}
SKIP_DIRS = {"源程序提取", "说明书章节", "旧版未裁剪材料", "旧命名兼容", "归档", "archive", "历史", "legacy", "补充声明"}


def grade(score):
    return "低（接近人工档）" if score < LOW else ("中（需抽查改写）" if score < HIGH else "高（模板化明显）")


def structure_penalty(text, reasons, raw=None):
    """朱雀校准出的结构信号：括号补注密度、粗体引导词、分号收尾。散文和列表共用。"""
    risk, n = 0, max(len(text), 1)
    paren = len(set(PAREN.findall(text))) * 1000 / n  # 去重：页眉里重复的（PC 端）只算一次
    if len(text) >= 80 and paren >= 10:
        risk += 30 if paren >= 15 else 20
        reasons.append(f"括号补注过密（每千字 {paren:.0f} 个，人工样本约 6）→ 只保留必要的，其余写进句子或挪进表格")
    raw = raw or text
    bold = len(BOLD_LEAD.findall(raw))
    if bold >= 2:
        risk += 20
        reasons.append(f"粗体引导词+冒号 {bold} 处 → 改为小标题或普通句子，别用“**X**：”排比")
    faq = len(FAQ_Q.findall(raw))
    if faq >= 2:
        risk += 25
        reasons.append(f"FAQ 模板（**Qn：…？** 共 {faq} 处）→ 改成“现象 → 先看哪里 → 怎么改”的排查叙述，问题之间写法错开")
    mid_n = len(re.findall(r"[;；](?!\s*$)", text, re.M))
    if mid_n >= 2 and mid_n * 1000 / n >= 6:
        risk += 10
        reasons.append("句中分号过多 → 拆成短句，用句号")
    semi = len(re.findall(r"[;；]\s*$", text, re.M))
    if semi >= 2:
        risk += 10
        reasons.append(f"{semi} 条以分号收尾的排比条目 → 句号结束，条目句式错开")
    return risk


def score_prose(b):
    text, reasons, risk = b.text, [], 25
    bl = blacklist_hits(text)
    if bl:
        risk += 18 * min(len(bl), 3)
        reasons += [f"黑名单句式「{hit}」→ {tip}" for _, hit, tip in bl[:4]]
    mk = marketing_hits(text)
    if mk:
        risk += 8 * min(len(mk), 3)
        reasons.append(f"营销词：{'、'.join(mk)} → 删掉或换成数据")
    facts = fact_hits(text)
    # 事实锚点保证真实性；朱雀实测它与判定几乎无相关（rho≈0），所以只罚缺失、不奖励堆砌
    if facts == 0 and len(text) >= 30:
        risk += 12
        reasons.append("无事实锚点（控件名/路径/版本号/错误码/数值约束）→ 读源码补一个真实事实")
    risk += structure_penalty(text, reasons, b.raw)
    sents = sentences(text)
    lens = [len(s) for s in sents]
    if len(sents) >= 4 and cv(lens) < 0.3:
        risk += 12
        reasons.append(f"句长过于均匀（{lens}）→ 长短句交错，插一个 10 字以内的短句")
    if len(sents) > 5:
        risk += 8
        reasons.append(f"段落 {len(sents)} 句，超过 5 句 → 拆段或转表格")
    first = sents[0] if sents else text
    for pat in TEMPLATE_OPENERS:
        if re.search(pat, first):
            risk += 10
            reasons.append("模板化开头（本系统采用/该模块负责/通过…实现）→ 改为操作视角开头")
            break
    abstract = len(re.findall(ABSTRACT_NOUNS, text))
    if len(text) >= 60 and abstract * 100 / len(text) >= 1.2:
        risk += 15
        reasons.append(f"抽象名词过密（能力/效率/场景/价值等 {abstract} 处）→ 换成控件名、字段、数值")
    enum = ENUM.findall(text)
    if enum and facts < 2 and abstract:
        risk += 10
        reasons.append(f"长顿号枚举「{enum[0][:24]}…」→ 只留真实用到的 2-3 项，或改表格")
    # FAQ 模板里的“失败时/请…”不算操作痕迹（朱雀实测 FAQ 段 0.92–0.996）
    if len(FAQ_Q.findall(b.raw)) < 2:
        ops = sum(1 for x in sents if is_operation(x))
        if ops:
            risk -= min(ops * 6, 18)
        if any(re.search(p, text) for p in EXPERIENCE):
            risk -= 8
    if PLACEHOLDER.search(text):
        risk += 30
        reasons.append("残留模板占位符（【待…】/按项目实际填写）→ 必须填真实内容")
    if len(text) < 25:
        risk = min(risk, 30)
    return max(0, min(100, risk)), reasons


def score_list(b):
    items, reasons, risk = b.items, [], 20
    n = len(items)
    op_ratio = sum(1 for i in items if is_operation(i) or "“" in i) / n if n else 0
    if op_ratio >= 0.5 and not BOLD_LEAD.search(b.text):
        # 操作步骤列表：朱雀实测 100% 判人工，句式相近是正常的，不按同构处罚
        risk = 10
    elif n >= 3:
        shapes = [item_shape(i) for i in items]
        leads = defaultdict(int)
        for s in shapes:
            leads[s[0]] += 1
        if max(leads.values()) / n >= 0.6:
            risk += 25
            reasons.append(f"{n} 条列表同一开头「{max(leads, key=leads.get)}」→ 至少改掉一半条目的句式")
        colons = sum(1 for s in shapes if s[1])
        if colons >= 3 and colons / n >= 0.75:
            risk += 15
            reasons.append(f"冒号定义式连用 {colons} 条（上限 2）→ 第三条起换结构或转表格")
        lens = [len(i) for i in items]
        if cv(lens) < 0.25:
            risk += 20
            reasons.append(f"条目长度过于整齐（{lens}）→ 有的写长有的一句带过")
        if sum(fact_hits(i) for i in items) / n < 0.3:
            risk += 15
            reasons.append("列表几乎没有具体事实 → 每条挂上文件/命令/数字")
    if op_ratio < 0.5 or BOLD_LEAD.search(b.text):
        risk += structure_penalty(b.text, reasons)
    bl = blacklist_hits(b.text)
    if bl:
        risk += 18 * min(len(bl), 3)
        reasons += [f"黑名单句式「{hit}」→ {tip}" for _, hit, tip in bl[:4]]
    mk = marketing_hits(b.text)
    if mk:
        risk += 8 * min(len(mk), 3)
        reasons.append(f"营销词：{'、'.join(mk)}")
    if PLACEHOLDER.search(b.text):
        risk += 30
        reasons.append("残留模板占位符 → 必须填真实内容")
    return max(0, min(100, risk)), reasons


def score_table(b):
    # 朱雀实测表格 0.24–0.997 都有，中位约 0.67：一律按“疑似”底分处理，不当作降分手段
    risk, reasons = 40, []
    bl = blacklist_hits(b.text)
    if bl:
        risk += 10 * min(len(bl), 3)
        reasons += [f"表格内黑名单句式「{hit}」" for _, hit, _ in bl[:3]]
    if PLACEHOLDER.search(b.text):
        risk += 30
        reasons.append("表格残留占位符（【待…】/按项目实际填写）")
    return min(100, risk), reasons


WEIGHT = {"prose": 1.0, "list": 1.0, "table": 1.0, "code": 0.3}


def analyze(path):
    blocks = load_blocks(path)
    heading_blocks = [b for b in blocks if b.kind == "heading"]
    scored = []
    for b in blocks:
        if b.kind == "heading" or b.chapter == "目录":
            continue
        if b.kind == "code":
            risk, reasons = 5, []
        else:
            risk, reasons = {"prose": score_prose, "list": score_list, "table": score_table}[b.kind](b)
        scored.append((b, risk, reasons))

    def weighted(rows):
        tw = sum(len(b.text) * WEIGHT[b.kind] for b, _, _ in rows)
        return round(sum(len(b.text) * WEIGHT[b.kind] * r for b, r, _ in rows) / tw, 1) if tw else 0.0

    chapters = defaultdict(list)
    for row in scored:
        chapters[row[0].chapter].append(row)
    full = "\n".join(b.text for b, _, _ in scored)
    heading_text = "\n".join(f"# {b.text}" for b in heading_blocks)
    heading_blacklist = blacklist_hits(heading_text)
    frequency = common_term_warnings(full)
    prose_chars = sum(len(b.text) for b, _, _ in scored if b.kind in ("prose", "list"))
    total_chars = sum(len(b.text) for b, _, _ in scored) or 1
    all_sents = [x for b, _, _ in scored if b.kind in ("prose", "list") for x in (b.items or sentences(b.text))]
    op_ratio = sum(1 for x in all_sents if is_operation(x)) / len(all_sents) if all_sents else 0
    dist = {"human": 0, "suspect": 0, "ai": 0}
    for b, r, _ in scored:
        if b.kind != "code":
            dist["human" if r < LOW else "suspect" if r < HIGH else "ai"] += len(b.text)
    dsum = sum(dist.values()) or 1
    base_score = weighted(scored)
    # 标题模板和全文高频词是跨段落风险，单个段落评分无法覆盖；仅作小幅加权，避免把专业术语直接判成 AI。
    overall_score = min(100.0, base_score + min(12, len(heading_blacklist) * 8)
                        + min(8, len(frequency) * 2))
    return {
        "file": str(path),
        "score": round(overall_score, 1),
        "distribution": {k: round(v * 100 / dsum, 1) for k, v in dist.items()},
        "grade": grade(overall_score),
        "stats": {
            "blocks": len(scored),
            "chars": total_chars,
            "prose_ratio": round(prose_chars / total_chars, 2),
            "facts_per_1k": round(fact_hits(full) * 1000 / total_chars, 1),
            "experience_marks": sum(len(re.findall(p, full)) for p in EXPERIENCE),
            "op_ratio": round(op_ratio, 2),
            "suspect_or_ai_ratio": round((dist["suspect"] + dist["ai"]) / dsum, 3),
            "blacklist_hits": len(blacklist_hits(full)),
            "heading_blacklist_hits": len(heading_blacklist),
            "common_terms": common_term_hits(full),
            "frequency_warnings": frequency,
            "placeholders": len(PLACEHOLDER.findall(full)),
        },
        "chapters": [{"chapter": c, "score": weighted(rows), "blocks": len(rows)} for c, rows in chapters.items()],
        "issues": [
            {"line": b.line, "chapter": b.chapter, "kind": b.kind, "score": r, "reasons": rs, "text": b.text}
            for b, r, rs in sorted(scored, key=lambda x: -x[1]) if rs and r >= LOW
        ],
    }


def collect(targets):
    files = []
    for t in map(Path, targets):
        if t.is_file():
            files.append(t)
            continue
        # 生成了正式材料清单后，目录扫描只读取“正文/填表复核/文档提交件”。
        # 程序源码 PDF 不参与 AIGC 文风评分，避免代码和旧版材料污染结果。
        formal = formal_material_paths(t)
        if formal:
            candidates = [t / "软件说明书.md", t / "申请表填报文案.md", t / "auto-fill" / "config.json"]
            doc_pdf = formal.get("docPdf")
            if doc_pdf and doc_pdf.suffix.lower() == ".pdf":
                candidates.append(doc_pdf)
            files.extend(p for p in candidates if p.is_file() and p.name not in SKIP_NAMES)
            continue
        for p in sorted(t.rglob("*")):
            if (not p.is_file() or p.name in SKIP_NAMES
                    or any(part in SKIP_DIRS for part in p.parts)
                    or p.name.endswith((".bak", ".backup"))):
                continue
            if p.suffix == ".md":
                files.append(p)
            elif p.suffix == ".json" and p.parent.name == "auto-fill" and p.name == "config.json":
                files.append(p)
            elif p.suffix == ".docx" and not p.with_suffix(".md").exists():
                files.append(p)
    return files


def render(results, top):
    out = ["# AIGC 文风检测报告", "",
           "> 本地启发式估计（规则见 references/aigc-detection.md），不等同于任何商业检测服务结论。",
           f"> 分档：<{LOW} 低 ｜ {LOW}-{HIGH} 中 ｜ ≥{HIGH} 高。目标：每份文件 < {LOW}，且无占位符残留。", "",
           "> 人工/疑似/AI 为按块分类后的字数占比（与朱雀报告同口径：占比不是“作者用 AI 的概率”）。", "",
           "## 总览", "",
           "| 文件 | 得分 | 档位 | 人工% | 疑似% | AI% | 疑似+AI | 操作句占比 | 事实/千字 | 黑名单 | 高频词 | 占位符 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        s, d = r["stats"], r["distribution"]
        freq = "、".join(f"{item['term']}{item['count']}次" for item in s.get("frequency_warnings", [])) or "—"
        out.append(f"| {r['file']} | {r['score']} | {r['grade']} | {d['human']} | {d['suspect']} | {d['ai']} "
                   f"| {s['suspect_or_ai_ratio']:.0%} | {s['op_ratio']:.0%} | {s['facts_per_1k']} | "
                   f"{s['blacklist_hits'] + s.get('heading_blacklist_hits', 0)} | {freq} | {s['placeholders']} |")
    for r in results:
        out += ["", f"## {r['file']}", "", "### 分章节", "", "| 章节 | 得分 | 块数 |", "| --- | --- | --- |"]
        out += [f"| {c['chapter']} | {c['score']} | {c['blocks']} |" for c in r["chapters"]]
        hints = []
        if r["stats"]["op_ratio"] < 0.25:
            hints.append(f"操作/条件句仅占 {r['stats']['op_ratio']:.0%}（朱雀判人工的手册约 40%）→ "
                         "功能描述后补“（二）操作步骤”：进入哪里 → 单击“X” → 失败时提示什么、怎么处理")
        if r["stats"]["facts_per_1k"] < 8:
            hints.append(f"事实密度 {r['stats']['facts_per_1k']}/千字偏低（建议 ≥8；它保证真实性，但单靠它不降分）")
        if r["stats"].get("frequency_warnings"):
            terms = "、".join(f"{item['term']} {item['count']} 次（{item['per_1k']}/千字）"
                              for item in r["stats"]["frequency_warnings"])
            hints.append(f"高频词：{terms} → 合并重复主语，改用真实页面、字段、接口名；不要只做同义词替换")
        if r["stats"].get("heading_blacklist_hits"):
            hints.append("发现通用优势/核心价值类章节标题 → 删除模板化总结，换成真实操作记录或源码证据")
        if hints:
            out += ["", "### 全文提示", ""] + [f"- {h}" for h in hints]
        issues = r["issues"][:top]
        out += ["", f"### 高风险块（前 {len(issues)} / 共 {len(r['issues'])}）", ""]
        for i, it in enumerate(issues, 1):
            snippet = it["text"].replace("\n", " / ")
            snippet = snippet[:160] + ("…" if len(snippet) > 160 else "")
            out += [f"**{i}. L{it['line']} ｜ {it['chapter']} ｜ {it['kind']} ｜ {it['score']} 分**", "",
                    f"> {snippet}", ""] + [f"- {x}" for x in it["reasons"]] + [""]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="软著材料 AIGC 文风检测")
    ap.add_argument("targets", nargs="+", help="文件（.md/.txt/.docx/.pdf/auto-fill config.json）或目录")
    ap.add_argument("--report", help="写出 Markdown 报告路径（默认打印到终端）")
    ap.add_argument("--json", help="写出 JSON 结果（供 aigc_rewrite.py 使用）")
    ap.add_argument("--top", type=int, default=20, help="每个文件列出多少个高风险块")
    ap.add_argument("--fail-above", type=float, help="任一文件得分超过该值或残留占位符时退出码为 1")
    ap.add_argument("--max-ai-ratio", type=float, help="任一文件 AI 档字数占比（%%）超过该值时退出码为 1")
    ap.add_argument("--max-suspect-ratio", type=float,
                    help="任一文件疑似 AI + AI 档字数占比超过该值时退出码为 1（本地结构指标，不等同朱雀）")
    args = ap.parse_args()

    files = collect(args.targets)
    if not files:
        sys.exit("没有找到可检测的文件")
    results = [analyze(f) for f in files]
    md = render(results, args.top)
    if args.report:
        Path(args.report).write_text(md, encoding="utf-8")
        print(f"报告已写入 {args.report}")
    else:
        print(md)
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        d = r["distribution"]
        print(f"{r['score']:>5}  {r['grade']:<10}  人工 {d['human']:>5}% 疑似 {d['suspect']:>5}% AI {d['ai']:>5}%  {r['file']}",
              file=sys.stderr)
    failed = False
    if args.fail_above is not None:
        failed |= any(r["score"] > args.fail_above or r["stats"]["placeholders"] for r in results)
    if args.max_ai_ratio is not None:
        failed |= any(r["distribution"]["ai"] > args.max_ai_ratio for r in results)
    if args.max_suspect_ratio is not None:
        failed |= any(r["stats"]["suspect_or_ai_ratio"] > args.max_suspect_ratio for r in results)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
