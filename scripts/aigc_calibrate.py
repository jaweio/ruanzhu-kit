#!/usr/bin/env python3
"""用朱雀（matrix.tencent.com/ai-detect）等外部检测的真实结果校准本地规则。

样本库：assets/aigc-calibration/labels.json + samples/*.md
每条样本 = 一段送检原文 + 外部检测给出的 AIGC ratio（0-1，≥0.5 视为非人工）。

用法：
  python3 aigc_calibrate.py                         # 回归自测：改完 aigc_rules/aigc_check 必跑
  python3 aigc_calibrate.py --import-report 报告.pdf  # 从朱雀导出的报告 PDF 批量导入分段样本
  python3 aigc_calibrate.py --add 原文.txt --ratio 0.1555 --note "第2批 人工"
  python3 aigc_calibrate.py --min-acc 0.75          # 准确率低于阈值时退出码 1

导入的原文会原样进入 skill 目录，导入前请确认已脱敏（产品名、人名、内网地址等）。
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aigc_check import LOW, analyze  # noqa: E402
from aigc_rules import pdf_text  # noqa: E402

LIB = Path(__file__).resolve().parents[1] / "assets" / "aigc-calibration"


def load_labels():
    f = LIB / "labels.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save_labels(labels):
    (LIB / "samples").mkdir(parents=True, exist_ok=True)
    (LIB / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_sample(labels, text, ratio, note, source):
    idx = max([int(re.sub(r"\D", "", x["file"]) or 0) for x in labels] + [0]) + 1
    name = f"samples/s{idx:03d}.md"
    (LIB / "samples").mkdir(parents=True, exist_ok=True)
    (LIB / name).write_text(text.strip() + "\n", encoding="utf-8")
    labels.append({"file": name, "ratio": ratio, "chars": len(text.strip()), "note": note,
                   "source": source, "added": date.today().isoformat()})
    return name


def parse_report(pdf):
    """朱雀报告 PDF → [(ratio, text)]。去掉页眉页脚和分段统计表。"""
    t = pdf_text(pdf)
    t = re.sub(r"(?m)^\d{1,2}/\d{1,2}/\d{2}, .*?report_\d+\s*$\n?", "", t)
    t = re.sub(r"(?m)^https://matrix\.tencent\.com/ai-detect/ \d+/\d+\s*$\n?", "", t)
    t = re.sub(r"(?m)^\d+ Segment\d+ [\d.]+% \d+ [\d.]+\s*$\n?", "", t)
    parts = re.split(r"\s*NO\. ?\d+\s+Segment\d+ AIGC ratio ([\d.]+)\s*\n", t)
    return [(float(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]


def evaluate(labels, verbose=True):
    rows = []
    for l in labels:
        r = analyze(LIB / l["file"])
        rows.append((l, r["score"]))
    n = len(rows)
    if not n:
        sys.exit("样本库为空")
    ok = sum((l["ratio"] >= 0.5) == (s >= LOW) for l, s in rows)
    hum = [(l, s) for l, s in rows if l["ratio"] < 0.5]
    ai = [(l, s) for l, s in rows if l["ratio"] >= 0.5]
    fp = sum(s >= LOW for _, s in hum)  # 人工样本被误判
    fn = sum(s < LOW for _, s in ai)    # AI 样本漏判

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0] * len(v)
        for k, i in enumerate(order):
            out[i] = k
        return out

    a, b = rank([l["ratio"] for l, _ in rows]), rank([s for _, s in rows])
    rho = 1 - 6 * sum((x - y) ** 2 for x, y in zip(a, b)) / (n * (n * n - 1)) if n > 2 else 0
    if verbose:
        print(f"{'样本':<18}{'外部':>7}{'本地':>7}  结果  备注")
        for l, s in rows:
            hit = (l["ratio"] >= 0.5) == (s >= LOW)
            print(f"{l['file']:<18}{l['ratio']:>7.3f}{s:>7.1f}  {'OK  ' if hit else 'MISS'}  {l.get('note', '')}")
    acc = ok / n
    print(f"\n样本 {n}（人工 {len(hum)} / 非人工 {len(ai)}）｜准确率 {acc:.0%}｜人工误判 {fp}｜AI 漏判 {fn}｜Spearman {rho:+.2f}")
    return acc, fp


def main():
    ap = argparse.ArgumentParser(description="AIGC 本地规则校准")
    ap.add_argument("--import-report", help="朱雀报告 PDF，按分段导入样本")
    ap.add_argument("--add", help="单个原文文件（.txt/.md），需配合 --ratio")
    ap.add_argument("--ratio", type=float, help="该原文的外部 AIGC ratio（0-1）")
    ap.add_argument("--note", default="", help="备注")
    ap.add_argument("--min-acc", type=float, help="准确率低于该值（0-1）时退出码 1")
    ap.add_argument("--max-fp", type=int, help="人工样本被误判数超过该值时退出码 1")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    labels = load_labels()
    if args.import_report:
        segs = parse_report(args.import_report)
        for ratio, text in segs:
            add_sample(labels, text, ratio, args.note or "朱雀分段", Path(args.import_report).name)
        save_labels(labels)
        print(f"导入 {len(segs)} 段 → {LIB}")
    if args.add:
        if args.ratio is None:
            sys.exit("--add 需要 --ratio")
        add_sample(labels, Path(args.add).read_text(encoding="utf-8"), args.ratio, args.note, Path(args.add).name)
        save_labels(labels)
    acc, fp = evaluate(labels, not args.quiet)
    if (args.min_acc is not None and acc < args.min_acc) or (args.max_fp is not None and fp > args.max_fp):
        sys.exit(1)


if __name__ == "__main__":
    main()
