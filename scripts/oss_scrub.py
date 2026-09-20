#!/usr/bin/env python3
"""开源 / 仓库痕迹清除：申报材料中一律不出现仓库地址与开源信息。

适用场景：自有项目先在 GitHub / Gitee 开源，之后申请软著。著作权人就是开源作者，
材料里的许可证头、仓库地址、Star/fork 字样都是自己留下的，清除后提交。

边界：
- 自有代码（版权行属于著作权人或 self_aliases）→ 清除许可证/版权头与仓库痕迹
- 第三方代码（版权行属于他人、第三方路径、压缩代码）→ 不清除他人声明，整份文件不取材
  （由 generate_source_docx.py 调用 third_party_reasons 自动跳过）
- 发表状态：一律按“未发表”处理——申报的是上架版本，与开源参考代码有本质区别；源程序须取自上架版本

命令行（清理说明书 / 申请表 / auto-fill 文案，默认预览）：
  python3 oss_scrub.py --config soft-copyright-materials/ruanzhu.config.json
  python3 oss_scrub.py --config ... --apply        # 写回，原文件留 .bak
  python3 oss_scrub.py 某文件.md --apply            # 单独处理某个文件
"""

import argparse
import difflib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from copyright_check import (COPYRIGHT_LINE, LICENSE_TEXT, REPO_URL, SCAFFOLDS, THIRD_PARTY_PATH,  # noqa: E402
                             holder_tokens)

# 清除范围只有三类：① 开源协议 ② 仓库/托管地址 ③ 引用来源。
# Star 评分、Issue 工单、fork()、PR、贡献者、社区、GitHub 登录等业务用语一律不动。

# ② 地址：代码托管、徽章、包平台、Star 统计等（都是指向开源项目的地址）
EXTRA_URL = re.compile(
    r"https?://(?:www\.)?(?:shields\.io|img\.shields\.io|badge\.fury\.io|travis-ci\.(?:org|com)|circleci\.com"
    r"|codecov\.io|coveralls\.io|star-history\.com|api\.star-history\.com|npmjs\.com/package|pypi\.org/project"
    r"|opencollective\.com|deepwiki\.com|gitpod\.io|app\.fossa\.com|sonarcloud\.io|pkg\.go\.dev"
    r"|readthedocs\.(?:io|org)|github\.io|gitee\.io)[^\s)\]\"'>，。]*", re.I)
SSH_REPO = re.compile(r"git@(?:github\.com|gitee\.com|gitlab\.com|bitbucket\.org|gitcode\.(?:com|net))[:/][\w./-]+", re.I)
# ③ 引用：博客 / 问答 / 代码片段站点的地址
REF_URL = re.compile(
    r"https?://(?:www\.)?(?:stackoverflow\.com|stackexchange\.com|segmentfault\.com|blog\.csdn\.net|csdn\.net"
    r"|juejin\.(?:cn|im)|cnblogs\.com|jianshu\.com|zhihu\.com|zhuanlan\.zhihu\.com|oschina\.net|51cto\.com"
    r"|codepen\.io|jsfiddle\.net|medium\.com|dev\.to|v2ex\.com|runoob\.com)[^\s)\]\"'>，。]*", re.I)
ANY_REPO = re.compile(f"(?:{REPO_URL.pattern}[^\\s)\\]\"'>，。]*)|(?:{EXTRA_URL.pattern})|(?:{SSH_REPO.pattern})"
                      f"|(?:{REF_URL.pattern})", re.I)

# ① 协议文本
LICENSE_WORDS = (
    r"SPDX-License-Identifier|Licen[sc]ed under|@license\b|\bMIT License\b|Apache License|Apache-2\.0"
    r"|GNU (?:Lesser |Affero )?General Public License|\b(?:A|L)?GPL-?v?\d|Mozilla Public License|BSD-\d-Clause"
    r"|Permission is hereby granted|Redistribution and use in source|THE SOFTWARE IS PROVIDED|WITHOUT WARRANTIES? OF ANY KIND"
    r"|木兰宽松许可证|Mulan PSL|(?:MIT|Apache|GPL|LGPL|AGPL|BSD|MPL|木兰)\s*(?:-?\d(?:\.\d)?)?\s*(?:开源)?(?:协议|许可证?|License)"
    r"|开源(?:协议|许可证?)")
# ③ 引用标记
REF_WORDS = (
    r"参考(?:自|了|于)|引用(?:自|了)|来源\s*[:：]|出处\s*[:：]|转载(?:自)?|摘(?:自|录自)|改编自|改写自|移植自|抄自|借鉴(?:自|了)"
    r"|forked from|fork(?:ed)? of\b|based on\s+(?!the\b|user|this|data|which|a\b)\S+|adapted from|ported from|copied from"
    r"|taken from|borrowed from|inspired by|derived from|credits?\s*[:：]|原作者|原项目|原仓库")
# 声明项目本身开源的表述（“开源信息”），不含“开源节流”等业务词
OSS_STATEMENT = (
    r"(?:已|完全|免费)?开源(?:于|在|到)|已开源|开源(?:地址|仓库|项目|版本?|免费|代码)|源码(?:地址|托管|已托管)"
    r"|(?:GitHub|Gitee|GitLab|码云|GitCode)\s*(?:上|中)?\s*(?:开源|仓库|主页|项目地址|托管|地址|源码)"
    r"|托管(?:在|于)\s*(?:GitHub|Gitee|GitLab|码云|GitCode)"
    r"|(?:欢迎|点个|给个|求)\s*(?:Star|⭐)")

# 代码注释：命中即删除该注释行（整行注释）或行尾注释
OSS_COMMENT = re.compile(f"{LICENSE_WORDS}|{REF_WORDS}|{OSS_STATEMENT}|All rights reserved|@copyright\\b", re.I)
COMMENT_ONLY = re.compile(r"^\s*(?://+|#+(?!include|define|if|endif|pragma|import)|\*+|/\*+|\*/|<!--|-->|--|;+|'''|\"\"\")")

# 文档：整节删除的标题（标题去掉编号后基本等于这些词才删，避免误伤“许可证管理”）
OSS_SECTION = re.compile(
    r"^(?:开源)?(?:协议|许可证?|许可协议|License|LICENSE|Licen[cs]ing)$|^开源(?:协议|许可|说明|地址|仓库)"
    r"|^(?:致谢|鸣谢|特别感谢|Acknowledge?ments?|Credits|Thanks|参考(?:资料|文献|项目|链接)?|References?|引用|相关链接"
    r"|Star\s*History|Stargazers(?:\s+over\s+time)?)$", re.I)
# 文档：整句删除
OSS_SENTENCE = re.compile(f"{LICENSE_WORDS}|{REF_WORDS}|{OSS_STATEMENT}", re.I)
BADGE_LINE = re.compile(r"^\s*(?:\[?!\[[^\]]*\]\([^)]*\)\]?(?:\([^)]*\))?\s*)+$")
SENT_END = re.compile(r"(?<=[。！？!?；;])")
# 去掉地址后残留的“详见 / see”
DANGLING = re.compile(r"[，,：:\s]*(?:详见|详情见|参见|参考|见|see|refer to|ref|link)\s*[:：]?\s*[。.,，]?\s*$", re.I)


# ------------------------------------------------------------------ 归属判断
def own_tokens(cfg, repo=None):
    """著作权人 + self_aliases + 本地 git 远程里的仓库所有者（仅当 self_open_source 为真）。"""
    toks = set(holder_tokens(cfg.get("copyright_holder", "")))
    toks |= {a for a in cfg.get("self_aliases", []) if a}
    if repo is not None and cfg.get("self_open_source"):
        from copyright_check import git
        for u in git(repo, "remote", "-v").split():
            m = re.search(r"(?:github\.com|gitee\.com|gitlab\.com|gitcode\.(?:com|net))[:/]([\w.-]+)/", u, re.I)
            if m:
                toks.add(m.group(1))
    return [t for t in toks if len(t) >= 2]


def _copyright_owners(head):
    owners = []
    for m in COPYRIGHT_LINE.finditer(head):
        who = re.sub(r"^[-–\s]*(?:present|now)?[,\s]*", "", m.group(1)).strip(" .")
        if who and not re.fullmatch(r"[\W\d]+", who) and not re.search(r"<?year>?|\[yyyy\]|\{\{", who, re.I):
            owners.append(who)
    return owners


def is_own(who, tokens):
    w = who.lower()
    return any(t.lower() in w for t in tokens)


def third_party_reasons(rel, text, tokens):
    """返回该文件不能取材的原因列表；空列表表示可以取材（自有或无声明）。"""
    reasons = []
    if THIRD_PARTY_PATH.search(rel):
        reasons.append("第三方/构建产物路径")
    lines = text.splitlines()
    if lines and (max(len(l) for l in lines) > 1000 or sum(len(l) for l in lines) / len(lines) > 250):
        reasons.append("压缩/打包代码")
    head = "\n".join(lines[:60])
    foreign = [w for w in _copyright_owners(head) if not is_own(w, tokens)]
    if foreign:
        reasons.append("他人版权声明：" + foreign[0][:40])
    for sname, pat in SCAFFOLDS:
        if pat.search(head) and not is_own(sname, tokens):
            reasons.append("开源脚手架代码：" + sname)
            break
    return reasons


# ------------------------------------------------------------------ 代码清除
def _header_end(lines):
    """文件开头第一个注释块的 [start, end)。块注释到 */ 为止；行注释到第一个非注释行或空行为止。"""
    i, n = 0, len(lines)
    while i < n and (lines[i].startswith("#!") or re.match(r"^#.*coding[:=]", lines[i]) or not lines[i].strip()):
        i += 1
    start = i
    if i >= n:
        return start, start
    first = lines[i].strip()
    closers = {"/*": "*/", "<!--": "-->", '"""': '"""', "\'\'\'": "\'\'\'"}
    for opener, closer in closers.items():
        if first.startswith(opener):
            if closer in first[len(opener):]:
                return start, i + 1
            i += 1
            while i < n and closer not in lines[i]:
                i += 1
            return start, min(i + 1, n)
    if re.match(r"^(?://|#(?!include|define|if|import|pragma)|--|;)", first):
        while i < n and re.match(r"^\s*(?://|#(?!include|define|if|import|pragma)|--|;)", lines[i]):
            i += 1
        return start, i
    return start, start


def strip_own_header(lines, tokens):
    """若文件头注释块含许可证/版权且都属于自有，则整块删除。返回 (lines, 是否删除)。"""
    start, end = _header_end(lines)
    if end <= start:
        return lines, False
    block = "\n".join(lines[start:end])
    has_license = any(re.search(p, block, re.I) for _, p, _ in LICENSE_TEXT) or re.search(
        r"Copyright|©|版权所有|All rights reserved|@license|@author|github|gitee", block, re.I)
    if not has_license:
        return lines, False
    if any(not is_own(w, tokens) for w in _copyright_owners(block)):
        return lines, False  # 含他人声明：不动（文件应已被跳过）
    rest = lines[:start] + lines[end:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return rest, True


def scrub_code_line(line):
    """返回清除后的行；返回 None 表示整行删除。"""
    if COMMENT_ONLY.match(line) and OSS_COMMENT.search(line):
        return None
    if ANY_REPO.search(line):
        if re.search(r"\bgit\s+(?:clone|remote|submodule|pull|push|fetch)\b|\b(?:npm|pnpm|yarn|pip|go)\s+(?:i|install|add|get)\b", line):
            return None  # 依赖仓库地址的命令，去掉地址后没有意义
        line = DANGLING.sub("", ANY_REPO.sub("", line)).rstrip()
        if COMMENT_ONLY.match(line) and not re.sub(r"[\W_]", "", COMMENT_ONLY.sub("", line)):
            return None
    # 行尾注释里的开源字样：只删注释部分
    m = re.search(r"(\s+//|\s+#)\s.*$", line)
    if m and OSS_COMMENT.search(m.group(0)):
        line = line[:m.start()]
    return line


def scrub_code(text, tokens):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines, header = strip_own_header(lines, tokens)
    out, dropped = [], 0
    for l in lines:
        s = scrub_code_line(l)
        if s is None:
            dropped += 1
        else:
            out.append(s)
    return out, {"header": header, "dropped": dropped}


# ------------------------------------------------------------------ 文档清除
def _drop_sentences(text):
    parts = SENT_END.split(text)
    kept = [p for p in parts if not (OSS_SENTENCE.search(p) or ANY_REPO.search(p)
                                     or any(pat.search(p) for _, pat in SCAFFOLDS))]
    return "".join(kept).strip(), len(parts) - len(kept)


def scrub_markdown(md):
    lines = md.split("\n")
    out, stats = [], {"sections": 0, "lines": 0, "sentences": 0, "urls": 0}
    skip_level, fence = 0, False
    for line in lines:
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            if not skip_level:
                out.append(line)
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", s) if not fence else None
        if h:
            level = len(h.group(1))
            if skip_level and level > skip_level:
                continue
            skip_level = 0
            title = re.sub(r"^[\d.、\s]+|^附录\s*[A-Z]\s*", "", h.group(2)).strip(" ：:")
            if OSS_SECTION.search(title):
                skip_level = level
                stats["sections"] += 1
                continue
            h2 = ANY_REPO.sub("", line)
            out.append(h2)
            continue
        if skip_level:
            continue
        if fence:
            new = scrub_code_line(line)
            if new is None:
                stats["lines"] += 1
                continue
            out.append(new)
            continue
        if BADGE_LINE.match(s) or (s and ANY_REPO.fullmatch(re.sub(r"^[-*+>]\s*|[<>()\[\]]", "", s))):
            stats["lines"] += 1
            continue
        if s.startswith("|"):
            if OSS_SENTENCE.search(s) or ANY_REPO.search(s):
                stats["lines"] += 1
                continue
            out.append(line)
            continue
        if not s:
            out.append(line)
            continue
        prefix = re.match(r"^(\s*(?:[-*+]|\d+[.)、])\s+|\s*>\s*)?", line).group(0)
        body = line[len(prefix):]
        before = body
        body = re.sub(r"\[([^\]]*)\]\((?:%s)\)" % ANY_REPO.pattern, r"\1", body)  # 链接只留文字
        body, n = _drop_sentences(body)
        stats["sentences"] += n
        if ANY_REPO.search(body):
            body = DANGLING.sub("", ANY_REPO.sub("", body))
            stats["urls"] += 1
        if not re.sub(r"[\W_]", "", body):
            if before.strip():
                stats["lines"] += 1
            continue
        out.append(prefix + body)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return text, stats


def scrub_plain(text):
    """申请表字段等纯文本：按句删除。"""
    new, n = _drop_sentences(text)
    return ANY_REPO.sub("", new), n


# ------------------------------------------------------------------ 命令行
def targets_from_config(cfg):
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    files = []
    for proj in cfg.get("projects", []):
        d = root / proj["id"]
        files += [d / "软件说明书.md", d / "申请表填报文案.md", d / "auto-fill" / "config.json"]
        if (d / "说明书章节").exists():
            files += sorted((d / "说明书章节").glob("*.md"))
    return [f for f in files if f.exists()]


def process(path, apply_changes):
    old = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(old)
        total = 0
        for sec in data.values():
            if isinstance(sec, dict):
                for k, v in sec.items():
                    if isinstance(v, str) and k not in ("programPdf", "docPdf"):
                        sec[k], n = scrub_plain(v)
                        total += n
        new = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        stats = {"sentences": total}
    else:
        new, stats = scrub_markdown(old)
    if new == old:
        return stats, ""
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"{path} (原)", f"{path} (清除后)", n=0))
    if apply_changes:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
        path.write_text(new, encoding="utf-8")
    return stats, diff


def main():
    ap = argparse.ArgumentParser(description="清除申报材料中的仓库地址与开源信息")
    ap.add_argument("files", nargs="*", help="要处理的 .md / auto-fill config.json；不传则按 --config 扫描")
    ap.add_argument("--config", help="ruanzhu.config.json")
    ap.add_argument("--apply", action="store_true", help="写回（留 .bak）；默认只预览 diff")
    args = ap.parse_args()
    files = [Path(f) for f in args.files]
    if args.config:
        files += targets_from_config(json.loads(Path(args.config).read_text(encoding="utf-8")))
    if not files:
        sys.exit("没有要处理的文件")
    for f in files:
        stats, diff = process(f, args.apply)
        if diff and not args.apply:
            print(diff)
        changed = {k: v for k, v in stats.items() if v}
        print(f"{'已清除' if args.apply and diff else '待清除' if diff else '无痕迹'}  {f}  {changed or ''}", file=sys.stderr)
    if not args.apply:
        print("（预览模式，加 --apply 写回）", file=sys.stderr)


if __name__ == "__main__":
    main()
