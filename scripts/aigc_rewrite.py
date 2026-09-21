#!/usr/bin/env python3
"""软著材料 AIGC 痕迹去除。分两层：

1. 机械清理（本脚本自动完成）：只做不改变事实、不破坏语法的替换——
   删营销形容词、删“值得注意的是/综上所述”、“包括但不限于”→“包括”、“进行配置”→“配置”等。
   默认 dry-run 只打印 diff，加 --apply 才写回（原文件备份为 .bak）。
2. 语义改写（交给 Claude / 人工）：生成《AIGC改写任务单.md》，逐段列出原文、问题、
   改写要求和需要去源码里查的事实。脚本不会编造任何事实。

只处理 .md 和 auto-fill/config.json；.docx 请改 .md 后重新生成。
代码块、行内代码不会被改动。

用法：
  python3 aigc_rewrite.py <材料目录>                 # 预览机械清理 + 生成任务单
  python3 aigc_rewrite.py <材料目录> --apply         # 写回
  python3 aigc_rewrite.py 软件说明书.md --apply --min-score 45
"""

import argparse
import difflib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aigc_check import LOW, analyze, collect  # noqa: E402

# (正则, 替换, 说明) —— 只放“删了/换了也不影响事实与语法”的规则
SAFE_RULES = [
    (r"可以(?=[，。；])", "可", "可以→可（仅减少口头化重复，不改变事实）"),
    (r"包括但不限于", "包括", "包括但不限于→包括"),
    (r"值得(?:注意|关注)的是[，,]?", "注意，", "值得注意的是→注意"),
    (r"值得一提的是[，,]?", "", "删“值得一提的是”"),
    (r"(?:综上所述|总而言之|总的来说)[，,]?", "", "删总结套话"),
    (r"(?:强大|完善|丰富|全面|卓越|领先|极致|优秀|先进)的", "", "删营销形容词"),
    (r"高效(?:地|的)(?=[一-龥])", "", "删“高效地/高效的”"),
    (r"显著(?=提升|提高|改善|降低)", "", "删“显著”"),
    (r"有效(?=保障|保证|提升|降低|解决)", "", "删“有效”"),
    (r"(?:一站式|全方位|多维度)的?", "", "删空泛修饰"),
    (r"进行(?=(?:配置|安装|部署|查询|修改|删除|保存|校验|管理|处理|统计|备份|编辑|上传|下载)(?![一-龥]{0,1}的))",
     "", "进行配置→配置"),
    (r"，从而(?=[一-龥])", "，", "删“从而”"),
    (r"旨在", "用于", "旨在→用于"),
    (r"致力于", "用于", "致力于→用于"),
]

# 按整行生效的规则：在代码块之外逐行执行（行内代码不影响行首/行尾匹配）
LINE_RULES = [
    (r"^(\s*(?:[-*+]|\d+[.)、])\s+.+?)[;；]\s*$", r"\1。", "列表条目分号收尾→句号"),
    (r"^(\s*(?:[-*+]|\d+[.)、])\s+)\*\*([^*\n]{1,24})\*\*\s*([:：])", r"\1\2\3", "去掉列表粗体引导词的加粗"),
]

# 旧版本生成器写入的整段通用模板。只在正文同时出现这些固定标志时裁剪，
# 不按章节编号盲删用户自己写的内容；新版 generate_docs.py 已不会再生成这些段落。
TEMPLATE_SECTION_RE = re.compile(r"(?ms)^(#{2,3})\s+([^\n]+)\n.*?(?=^#{2,3}\s+|\Z)")


def prune_template_sections(text):
    hits = {}

    def replace(match):
        title = re.sub(r"^\d+(?:\.\d+)*\s*", "", match.group(2)).strip()
        body = match.group(0)
        remove = False
        if title == "设计原则" and all(x in body for x in ("易用性", "模块化", "可扩展性", "安全性", "可追溯")):
            remove = True
        elif title == "适用场景" and all(x in body for x in ("日常业务处理和任务管理", "企业或团队内部工具化应用")):
            remove = True
        elif title == "分层架构" and all(x in body for x in ("表现层", "业务层", "服务层", "数据层")):
            remove = True
        elif title == "硬件环境" and all(x in body for x in ("CPU", "双核及以上", "内存", "存储")):
            remove = True
        elif title == "权限要求" and all(x in body for x in ("文件访问", "网络访问", "日志访问")):
            remove = True
        elif title == "安装前准备" and "确认操作系统和运行环境满足要求" in body:
            remove = True
        elif title == "配置概述" and "软件配置包括基础参数、业务参数、运行参数、安全参数和扩展参数" in body:
            remove = True
        elif title == "快速上手" and all(x in body for x in ("启动软件", "完成基础配置", "进入核心功能页面")):
            remove = True
        elif title == "日志与监控" and "软件应记录启动、配置、核心操作、异常和关键状态变更日志" in body:
            remove = True
        elif title == "数据与缓存管理" and "定期检查数据文件、缓存目录、日志目录和临时文件" in body:
            remove = True
        elif title == "安全策略" and "对敏感配置、账号密钥、用户数据和关键操作进行权限控制" in body:
            remove = True
        elif title in {"软件无法启动怎么办？", "配置不生效怎么办？", "功能执行失败怎么办？"}:
            remove = True
        elif title == "测试用例" and all(x in body for x in ("TC-001", "TC-002", "TC-003")):
            remove = True
        if remove:
            hits[f"删除旧版通用模板：{title}"] = hits.get(f"删除旧版通用模板：{title}", 0) + 1
            return ""
        return body

    # 版本信息中只有申请表字段属于错误位置，源码范围仍保留。
    def clean_version(match):
        title = re.sub(r"^\d+(?:\.\d+)*\s*", "", match.group(2)).strip()
        body = match.group(0)
        if title != "版本信息" or not all(x in body for x in ("著作权人", "开发完成日期", "首次发表日期")):
            return body
        lines = [line for line in body.splitlines()
                 if not re.search(r"著作权人|开发完成日期|首次发表日期", line)]
        hits["删除说明书中的申请人字段：著作权人/日期"] = 1
        return "\n".join(lines) + "\n"

    text = TEMPLATE_SECTION_RE.sub(clean_version, text)
    return TEMPLATE_SECTION_RE.sub(replace, text), hits

# 任务单里的改写配方：原因关键词 → 怎么改 + 示范。示范来自朱雀实测判人工的写法（references/writing-style.md 第八节）
RECIPES = [
    ("括号补注", "括号只留必须的（单位、缩写全称）；类名/行数/错误码写进句子主干或挪进表格。",
     "✗ 战斗管理器（BattleMgr，约 1260 行）负责回合推进（含胜负判定）。\n"
     "✓ 回合推进和胜负判定都在 BattleMgr 里，这个类有 1260 行左右。"),
    ("粗体引导词", "“**X**：说明”连排改为三级标题 + 段落，或改成操作步骤。",
     "✗ **武将招募**：在招募模块消耗货币抽取武将……\n"
     "✓ ### 武将招募\n进入“招募”界面，选择招募类型后单击“招募”。次数用完时提示 14026。"),
    ("FAQ 模板", "不要“**Qn：…？**+答案”连排；改成表格（现象/可能原因/处理方法）或按排查顺序写。",
     "✓ | 问题现象 | 可能原因 | 处理方法 |\n| 登录后停在加载页 | 资源组未下载完 | 检查网络后重新进入 |"),
    ("黑名单", "整句删掉概括，换成“用户做了什么 → 系统做了什么”。",
     "✗ 通过预设化管理，系统将一次配置沉淀为可持续复用的展示方案。\n"
     "✓ 在“预设配置”里保存一次大屏地址和顺序，之后屏幕轮播、多屏切换都能直接选这个预设。"),
    ("抽象名词", "每个“能力/效率/场景”换成控件名、字段名或数值。",
     "✗ 多屏预览功能强调并行查看能力。\n✓ 多屏预览可选单屏、双屏、四屏、六屏或九屏布局。"),
    ("操作", "补“（二）操作步骤”：进入菜单 → 单击控件 → 系统反馈 → 失败分支。",
     "✓ 1. 在左侧菜单选择“大屏预览 > 投屏工具”。\n"
     "   2. 首次使用时按浏览器提示允许窗口管理权限；不支持时页面显示兼容性提示，改用较新版本的 Chrome 或 Edge。"),
    ("无事实锚点", "回源码/界面找一个真实值：控件文字、字段长度限制、可选项、版本号、错误码。查不到就删掉这句。", ""),
    ("通用优势章节", "删除“系统优势/技术优势/功能优势/应用优势/核心价值”等模板标题，改成真实操作、接口返回或日志结果；不要只换同义词。", ""),
    ("整套业务闭环", "删掉结论式评价，按真实入口 → 处理 → 返回结果 → 失败分支写，缺哪一步就不写哪一步。", ""),
    ("高频词", "先合并重复主语和重复章节，再用真实页面、字段、接口名替代泛称；不要机械地把“系统”全部替换成“平台”。", ""),
    ("长顿号枚举", "只留真正实现了的 2–3 项；可选项枚举（如 3/5/10/15 秒）可以保留。", ""),
    ("句长", "拆一个长句，或合并两个短句，让相邻句子长短明显不同。", ""),
    ("列表", "条目开头换动词或换主语；有的条目带条件分支，有的只写一句。", ""),
]


def recipes_for(reasons):
    out, seen = [], set()
    for key, how, demo in RECIPES:
        if key in seen:
            continue
        if any(key in r for r in reasons):
            seen.add(key)
            out.append(f"- **{key}**：{how}")
            if demo:
                out += ["", "  ```text", *["  " + x for x in demo.split("\n")], "  ```"]
    return out

PROTECT = re.compile(r"```.*?```|`[^`\n]+`", re.S)


def clean_text(text):
    """对非代码部分应用 SAFE_RULES，返回 (新文本, 命中计数)。"""
    hits, parts, last = {}, [], 0

    def apply(seg):
        seg, template_hits = prune_template_sections(seg)
        for note, n in template_hits.items():
            hits[note] = hits.get(note, 0) + n
        for pat, rep, note in SAFE_RULES:
            seg, n = re.subn(pat, rep, seg)
            if n:
                hits[note] = hits.get(note, 0) + n
        return re.sub(r"，，|，。", lambda m: "。" if m.group(0) == "，。" else "，", seg)

    lines, fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            for pat, rep, note in LINE_RULES:
                line, n = re.subn(pat, rep, line)
                if n:
                    hits[note] = hits.get(note, 0) + n
        lines.append(line)
    text = "\n".join(lines)

    for m in PROTECT.finditer(text):
        parts.append(apply(text[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(apply(text[last:]))
    return "".join(parts), hits


def clean_file(path, apply_changes):
    old = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(old)
        hits = {}
        for fields in data.values():
            if isinstance(fields, dict):
                for k, v in fields.items():
                    if isinstance(v, str) and len(v) >= 30:
                        fields[k], h = clean_text(v)
                        for x, n in h.items():
                            hits[x] = hits.get(x, 0) + n
        new = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    else:
        new, hits = clean_text(old)
    if new == old:
        return hits, ""
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"{path} (原)", f"{path} (清理后)", n=0))
    if apply_changes:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
        path.write_text(new, encoding="utf-8")
    return hits, diff


def task_sheet(results, min_score):
    out = ["# AIGC 改写任务单", "",
           "> 机械清理之后仍然偏模板化的段落。逐条改写，改完重跑 `aigc_check.py` 复测。",
           "> 改写纪律（摘自 references/writing-style.md）：",
           "> 1. 每段至少一个**从源码里查到的**事实（路径/类名/配置项/错误码/实测数字），查不到就写少一点，**禁止编造**；",
           "> 2. 能力罗列 → 操作动线（进入哪里 → 点什么 → 系统反馈 → 失败时提示什么、怎么处理）；",
           "> 3. 长短句交错，列表条目句式错开，冒号定义式最多连用 2 条；",
           "> 4. 优先写操作动线和失败分支（朱雀实测唯一稳定判人工的写法），口语化不是必需；",
           "> 5. 能表格化的（参数、环境、错误码、目录）直接改表格。",
           "> 6. 申请表 mainFunction 改写后仍需保持 500–1300 字，只写本软著的功能。", ""]
    n = 0
    for r in results:
        issues = [i for i in r["issues"] if i["score"] >= min_score]
        if not issues:
            continue
        out += [f"## {r['file']}（当前 {r['score']} 分，{r['grade']}）", ""]
        for it in issues:
            n += 1
            out += [f"### T{n:03d} ｜ L{it['line']} ｜ {it['chapter']} ｜ {it['kind']} ｜ {it['score']} 分", "",
                    "**原文**", "", "```text", it["text"], "```", "", "**问题**", ""]
            out += [f"- {x}" for x in it["reasons"]]
            recipe = recipes_for(it["reasons"])
            if recipe:
                out += ["", "**改法**", ""] + recipe
            out += ["", "**改写要求**", "", f"- 围绕「{it['chapter']}」，去源码中找到与本段对应的文件/函数/配置，挑 1-3 个真实事实写进去",
                    "- 保持原意与事实边界，不新增源码中不存在的功能", "- 改后文本：", "", "```text", "（在此填写）", "```", ""]
    if n == 0:
        out.append("没有需要语义改写的段落。")
    return "\n".join(out) + "\n", n


def main():
    ap = argparse.ArgumentParser(description="软著材料 AIGC 痕迹去除（机械清理 + 改写任务单）")
    ap.add_argument("targets", nargs="+", help="文件或材料目录")
    ap.add_argument("--apply", action="store_true", help="写回机械清理结果（生成 .bak 备份）")
    ap.add_argument("--min-score", type=float, default=LOW, help="任务单收录的最低风险分（默认 %(default)s）")
    ap.add_argument("--tasks", help="任务单输出路径（默认写到第一个目录下 AIGC改写任务单.md）")
    args = ap.parse_args()

    files = [f for f in collect(args.targets) if f.suffix in (".md", ".json")]
    if not files:
        sys.exit("没有找到可处理的 .md / auto-fill config.json")

    total = {}
    for f in files:
        hits, diff = clean_file(f, args.apply)
        for k, v in hits.items():
            total[k] = total.get(k, 0) + v
        if diff and not args.apply:
            print(diff)
    print("机械清理：" + ("、".join(f"{k}×{v}" for k, v in total.items()) or "无命中")
          + ("（已写回，原文件备份为 .bak）" if args.apply and total else "（预览，未写回；加 --apply 生效）" if total else ""),
          file=sys.stderr)

    # 任务单基于“清理后”的文本：未 --apply 时在内存里清理再评估
    results = []
    for f in files:
        if args.apply or f.suffix == ".json":
            results.append(analyze(f))
        else:
            tmp = f.with_name(f".aigc-preview-{f.name}")
            tmp.write_text(clean_text(f.read_text(encoding="utf-8"))[0], encoding="utf-8")
            try:
                r = analyze(tmp)
                r["file"] = str(f)
                results.append(r)
            finally:
                tmp.unlink()
    sheet, n = task_sheet(results, args.min_score)
    first = Path(args.targets[0])
    dest = Path(args.tasks) if args.tasks else (first if first.is_dir() else first.parent) / "AIGC改写任务单.md"
    dest.write_text(sheet, encoding="utf-8")
    print(f"改写任务单：{dest}（{n} 条）", file=sys.stderr)
    for r in results:
        print(f"{r['score']:>5}  {r['grade']:<10}  {r['file']}", file=sys.stderr)


if __name__ == "__main__":
    main()
