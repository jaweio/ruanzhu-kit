#!/usr/bin/env python3
"""源程序鉴别材料的安全裁剪工具。

这里只处理输出副本：默认移除注释、导入声明和多余空行，但不写回项目源文件。
"""

import re
from pathlib import Path


IMPORT_START = {
    ".go": re.compile(r"^\s*import\b"),
    ".py": re.compile(r"^\s*(?:from\s+\S+\s+import\b|import\b)"),
    ".js": re.compile(r"^\s*import\b"),
    ".jsx": re.compile(r"^\s*import\b"),
    ".ts": re.compile(r"^\s*import\b"),
    ".tsx": re.compile(r"^\s*import\b"),
    ".java": re.compile(r"^\s*import\b"),
    ".kt": re.compile(r"^\s*import\b"),
    ".kts": re.compile(r"^\s*import\b"),
    ".swift": re.compile(r"^\s*import\b"),
    ".dart": re.compile(r"^\s*import\b"),
    ".rs": re.compile(r"^\s*use\b"),
    ".cs": re.compile(r"^\s*using\s+(?:static\s+)?(?!var\b|\()[A-Za-z_][\w.\\]*(?:\s*;)\s*$"),
    ".php": re.compile(r"^\s*use\s+[A-Za-z_\\]"),
    ".c": re.compile(r"^\s*#\s*include\b"),
    ".h": re.compile(r"^\s*#\s*include\b"),
    ".cc": re.compile(r"^\s*#\s*include\b"),
    ".cpp": re.compile(r"^\s*#\s*include\b"),
    ".hpp": re.compile(r"^\s*#\s*include\b"),
}


def _comment_style(path):
    ext = Path(path).suffix.lower()
    hash_comments = ext in {".py", ".pyw", ".rb", ".sh", ".bash", ".yaml", ".yml", ".toml"}
    sql_comments = ext in {".sql"}
    html_comments = ext in {".html", ".htm", ".vue", ".xml"}
    return hash_comments, sql_comments, html_comments


def strip_comments(lines, path):
    """删除代码注释但保留字符串；返回 (行, 删除注释行数)。"""
    hash_comments, sql_comments, html_comments = _comment_style(path)
    out, removed = [], 0
    block_closer = None
    quote = ""
    for original in lines:
        result = []
        i = 0
        while i < len(original):
            if block_closer:
                end = original.find(block_closer, i)
                if end < 0:
                    i = len(original)
                    continue
                i = end + len(block_closer)
                block_closer = None
                continue
            if quote:
                result.append(original[i])
                if original[i] == "\\" and i + 1 < len(original):
                    result.append(original[i + 1])
                    i += 2
                    continue
                if original[i] == quote:
                    quote = ""
                i += 1
                continue
            if original.startswith("/*", i):
                block_closer = "*/"
                i += 2
                continue
            if original.startswith("<!--", i) and html_comments:
                end = original.find("-->", i + 4)
                if end < 0:
                    block_closer = "-->"
                    i = len(original)
                else:
                    i = end + 3
                continue
            if original.startswith("//", i) or (original.startswith("--", i) and sql_comments):
                break
            if original[i] == "#" and hash_comments:
                break
            if original[i] in {"'", '"', "`"}:
                quote = original[i]
            result.append(original[i])
            i += 1
        cleaned = "".join(result).rstrip()
        if cleaned.strip():
            out.append(cleaned)
        elif original.strip():
            removed += 1
        else:
            out.append("")
    return out, removed


def _balanced(line, opening, closing):
    return line.count(opening) - line.count(closing)


def strip_imports(lines, path):
    """移除 import/include/use 声明及其多行块；不影响业务代码。"""
    pattern = IMPORT_START.get(Path(path).suffix.lower())
    if not pattern:
        return lines, 0
    out, removed = [], 0
    depth = 0
    for line in lines:
        if depth:
            removed += 1
            depth += _balanced(line, "(", ")") + _balanced(line, "{", "}")
            if depth <= 0:
                depth = 0
            continue
        if pattern.match(line):
            removed += 1
            depth = _balanced(line, "(", ")") + _balanced(line, "{", "}")
            continue
        out.append(line)
    return out, removed


def compact_blank_lines(lines, max_blank_lines=1):
    out, blanks = [], 0
    for line in lines:
        if line.strip():
            blanks = 0
            out.append(line)
        elif blanks < max_blank_lines:
            out.append("")
            blanks += 1
    while out and not out[-1].strip():
        out.pop()
    return out
