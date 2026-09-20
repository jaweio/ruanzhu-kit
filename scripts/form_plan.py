#!/usr/bin/env python3
"""把申请表字段变成浏览器操作清单，并在填完后核对页面上的实际值。

填表由 Claude 通过浏览器插件（Claude in Chrome / computer-use）在用户已登录的 Chrome 里操作，
不用 Playwright、不开无头浏览器。本脚本负责两件机器能做准的事：

  1. plan：按 assets/r11-field-map.json 逐步列出「定位哪个控件 → 填什么值 → 怎么回读核对」，
     长文本单独落盘成 .txt，便于粘贴时不被转义搞乱。
  2. verify：把从页面回读到的值（JSON）与 config.json 比对，逐字段给出一致 / 不一致 / 缺失。

用法：
  python3 form_plan.py --config <材料目录>/auto-fill/config.json                 # 打印操作计划
  python3 form_plan.py --config ... --out 填表操作计划.md                        # 写成文件
  python3 form_plan.py --config ... --verify 回读.json                           # 核对页面实际值
"""

import argparse
import json
import re
import sys
from pathlib import Path

MAP = Path(__file__).resolve().parents[1] / "assets" / "r11-field-map.json"
PLACEHOLDER = re.compile(r"【[^】]*】")


def chars(s):
    return len(re.sub(r"\s", "", str(s or "")))


def dig(cfg, dotted):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def display(value, field):
    if field.get("map") and not isinstance(value, str):
        return field["map"][str(value).lower()]
    return value


def plan(cfg, fmap, cfg_path, long_dir):
    out = [f"# 申请表填表操作计划（{cfg.get('_project', '')}）", "",
           f"> 地址：{fmap['url']}", f"> **{fmap['stop_rule']}**",
           "> 值一律来自 `auto-fill/config.json`，页面上不即兴编写内容；任何字段对不上就停下问用户。", "",
           "## 操作前", "",
           "1. 由**用户本人**在 Chrome 里登录中国版权保护中心账号；agent 不碰账号密码。",
           "2. 确认浏览器里是正确的著作权人账户。",
           f"3. 手边打开配置：`{cfg_path}`", ""]
    longs = []
    for st in fmap["steps"]:
        out += [f"## 第 {st['step']} 步：{st['title']}", "",
                f"等待页面出现「{st['wait_for']}」后再操作。", ""]
        if st["fields"]:
            out += ["| 控件 | 类型 | 要填的值 | 核对 |", "| --- | --- | --- | --- |"]
        for f in st["fields"]:
            raw = dig(cfg, f["key"])
            val = display(raw, f)
            n = chars(val)
            note = f.get("note", "")
            if f["type"] == "file":
                target = (Path(cfg_path).parent / str(val)).resolve()
                shown = f"`{target}`" + ("" if target.exists() else " ❌文件不存在")
            elif f["type"] == "textarea" and n > 120:
                name = f["key"].split(".")[-1] + ".txt"
                longs.append((name, str(val)))
                shown = f"{n} 字长文本 → 见 `{long_dir}/{name}`（整段粘贴，勿手打）"
            elif val is None:
                shown = "⚠️ 配置里没有这个字段"
            else:
                shown = f"`{val}`"
            checks = []
            if f.get("limit") and isinstance(val, str) and n > f["limit"]:
                checks.append(f"❌超长 {n}/{f['limit']}")
            if f.get("min") and isinstance(val, str) and n < f["min"]:
                checks.append(f"❌不足 {n}/{f['min']}")
            if isinstance(val, str) and PLACEHOLDER.search(val):
                checks.append("❌占位符未填")
            if f.get("verify"):
                checks.append("填完回读")
            out.append(f"| {f['label']} | {f['type']} | {shown} | {'；'.join(checks) or '—'}"
                       + (f"<br>{note}" if note else "") + " |")
        if st.get("actions"):
            out += ["", "动作："] + [f"{i}. {a}" for i, a in enumerate(st["actions"], 1)]
        if st.get("forbidden"):
            out += ["", f"**禁止点击**：{'、'.join(st['forbidden'])}——由用户本人提交。"]
        if st.get("next"):
            out += ["", f"填完并回读无误后，点击「{st['next']}」。"]
        out.append("")
    out += ["## 填完之后", "",
            "1. 在确认页逐项回读，按下面的格式记下页面实际值：",
            "",
            "```json",
            '{"softwareName": "…", "version": "…", "completionDate": "…", "sourceLines": "…", "mainFunction": "…"}',
            "```",
            "",
            "2. 跑核对：`python3 scripts/form_plan.py --config <config.json> --verify 回读.json`",
            "3. 全部一致后点「保存至草稿箱」，然后把浏览器交回用户，由用户点「确认填报」。", ""]
    return "\n".join(out), longs


def verify(cfg, fmap, actual):
    rows, bad = [], 0
    for st in fmap["steps"]:
        for f in st["fields"]:
            short = f["key"].split(".")[-1]
            if short not in actual:
                continue
            want = str(display(dig(cfg, f["key"]), f) or "")
            got = str(actual[short])
            if f["type"] == "file":
                ok = Path(want).name.lower() in got.lower()
            elif f["type"] == "textarea" and chars(want) > 120:
                ok = chars(got) == chars(want)          # 长文本比字数，防止被截断
            else:
                ok = re.sub(r"\s", "", want) == re.sub(r"\s", "", got)
            bad += 0 if ok else 1
            rows.append((f["label"], "一致" if ok else "不一致",
                         (want[:40] + "…") if len(want) > 40 else want,
                         (got[:40] + "…") if len(got) > 40 else got))
    missing = [f["key"].split(".")[-1] for st in fmap["steps"] for f in st["fields"]
               if f.get("verify") and f["key"].split(".")[-1] not in actual]
    print(f"{'字段':<14}{'结果':<8}{'应填':<44}页面实际")
    for label, res, want, got in rows:
        print(f"{label:<14}{res:<8}{want:<44}{got}")
    if missing:
        print(f"\n必须回读但没给出的字段：{'、'.join(missing)}")
    print(f"\n共 {len(rows)} 项，{bad} 项不一致" + ("；必须改到一致再保存草稿" if bad else "；可以保存草稿"))
    return bad or len(missing)


def main():
    ap = argparse.ArgumentParser(description="申请表浏览器填表计划与核对")
    ap.add_argument("--config", required=True, help="<材料目录>/auto-fill/config.json")
    ap.add_argument("--out", help="操作计划输出路径（默认打印）")
    ap.add_argument("--verify", help="页面回读值 JSON")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    fmap = json.loads(MAP.read_text(encoding="utf-8"))

    if args.verify:
        actual = json.loads(Path(args.verify).read_text(encoding="utf-8"))
        sys.exit(1 if verify(cfg, fmap, actual) else 0)

    long_dir = cfg_path.parent / "长文本"
    text, longs = plan(cfg, fmap, cfg_path, long_dir.name)
    if longs:
        long_dir.mkdir(parents=True, exist_ok=True)
        for name, content in longs:
            (long_dir / name).write_text(content, encoding="utf-8")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(Path(args.out).resolve())
    else:
        print(text)
    if longs:
        print(f"长文本已落盘：{long_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
