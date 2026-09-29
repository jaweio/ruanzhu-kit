#!/usr/bin/env python3
"""源程序 HTML/PDF 的共用内容闸门，不依赖材料生成器。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


class SourceValidationError(ValueError):
    """源程序材料为空白、损坏或与打印输入不一致。"""


def _compact(text: str) -> str:
    return "".join(text.split())


_LATIN_LIGATURES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
})


# 部首补充区没有 NFKC 映射，只收录 macOS 中文字体常见的简体字形
_RADICAL_SUPPLEMENT = {"⻚": "页", "⻓": "长", "⻔": "门", "⻢": "马", "⻜": "飞", "⻛": "风",
                       "⻅": "见", "⻋": "车", "⻝": "食", "⻉": "贝", "⻓": "长", "⻩": "黄", "⻬": "齐"}


def _restore_radicals(text: str) -> str:
    """Chromium 在 macOS 上可能把汉字记成外观相同的部首字符（如“子”→“⼦”）。
    只还原康熙部首区（U+2F00–2FDF，NFKC 有标准映射）和部首补充区常见字形，
    不对其他字符做 NFKC，避免掩盖全角标识符等真实差异。"""
    import unicodedata
    out = []
    for ch in text:
        code = ord(ch)
        if 0x2F00 <= code <= 0x2FDF:
            ch = unicodedata.normalize("NFKC", ch)
        elif 0x2E80 <= code <= 0x2EFF:
            ch = _RADICAL_SUPPLEMENT.get(ch, ch)
        out.append(ch)
    return "".join(out)


def _comparison_text(text: str) -> str:
    # Helvetica/Chromium may extract a rendered ligature as one Unicode glyph.
    # Restrict normalization to these seven glyphs: NFKC could conceal real
    # source differences such as fullwidth identifiers or circled digits.
    return _compact(_restore_radicals(text.translate(_LATIN_LIGATURES)))


class _SourceHTMLParser(HTMLParser):
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pages: list[list[str]] = []
        self._stack: list[tuple[str, str]] = []
        self._rows: list[str] | None = None
        self._row: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        classes = set(" ".join(value or "" for key, value in attrs if key == "class").split())
        is_page = "source-page" in classes
        is_row = "source-line" in classes
        if is_page:
            if tag != "section" or self._rows is not None or is_row:
                raise SourceValidationError("源程序 HTML 的 source-page 必须是独立且不嵌套的 section。")
            self._rows = []
            self._stack.append((tag, "page"))
            return
        if is_row:
            if tag != "div" or self._rows is None or self._row is not None:
                raise SourceValidationError("源程序 HTML 的 source-line 必须是页内独立的 div。")
            self._row = []
            self._stack.append((tag, "row"))
            return
        if self._row is not None:
            raise SourceValidationError("源程序 HTML 的源码行含未转义的 HTML 标签。")
        if self._rows is not None and tag not in self._VOID_TAGS:
            self._stack.append((tag, "container"))

    def handle_endtag(self, tag):
        if not self._stack or tag in self._VOID_TAGS:
            return
        opened, kind = self._stack.pop()
        if opened != tag:
            raise SourceValidationError("源程序 HTML 的页面或源码行标签未正确闭合。")
        if kind == "row":
            self._rows.append("".join(self._row))
            self._row = None
        elif kind == "page":
            page_number = len(self.pages) + 1
            if not self._rows:
                raise SourceValidationError(f"源程序 HTML 第 {page_number} 页没有源码行。")
            if not any(_compact(row) for row in self._rows):
                raise SourceValidationError(f"源程序 HTML 第 {page_number} 页为空白（只有空格或 &nbsp;）。")
            self.pages.append(self._rows)
            self._rows = None

    def handle_data(self, data):
        if self._row is not None:
            self._row.append(data)


def parse_source_html(html: str) -> list[list[str]]:
    """校验 source-page/source-line 结构，返回逐页、解码后的原始源码行。

    有源码的页允许保留空行，但任何整页空行、缺行或未闭合标签均拒绝。
    """
    parser = _SourceHTMLParser()
    parser.feed(html)
    parser.close()
    if parser._stack:
        raise SourceValidationError("源程序 HTML 的页面或源码行标签未正确闭合。")
    if not parser.pages:
        raise SourceValidationError("源程序 HTML 没有 source-page 源码页。")
    return parser.pages


_COUNTER_ONLY = re.compile(r"(?:\d+(?:/\d+)?|第\d+页(?:共\d+页)?|page\d+(?:of\d+)?)", re.IGNORECASE)


def _is_blank_source(text: str) -> bool:
    compact = _compact(text)
    return not compact or _COUNTER_ONLY.fullmatch(compact) is not None


def _is_margin_line(line: str, page_number: int, header: str | None) -> bool:
    """页边距行：独占一行的页码，或“页眉 + 页码”（页眉与页码同在顶部，提取时常合成一行）。"""
    compact = _comparison_text(line)
    counter = str(page_number)
    if compact == counter:
        return True
    return bool(header) and compact == _comparison_text(header) + counter


def _page_text_candidates(text: str, page_number: int, header: str | None = None) -> set[str]:
    """只允许移除首行或末行的页码（可带页眉），保留源码中的数字。"""
    lines = [line for line in text.splitlines() if _compact(line)]
    candidates = {_comparison_text(text)}
    if lines and _is_margin_line(lines[0], page_number, header):
        candidates.add(_comparison_text("".join(lines[1:])))
    if lines and _is_margin_line(lines[-1], page_number, header):
        candidates.add(_comparison_text("".join(lines[:-1])))
    return candidates


def validate_source_pdf(path, expected_pages=None, expected_count=None, require_page_numbers=False,
                        header=None) -> dict:
    """逐页拒绝空白 PDF，并可与 HTML 源码逐字符核对（忽略空白、展开拉丁连字）。

    ``expected_pages`` 使用 ``parse_source_html`` 返回的 ``list[list[str]]``；
    ``expected_count`` 是独立的期望页数。成功返回 ``pages`` 和
    ``nonblank_pages``，两者均为页数；失败抛出 ``SourceValidationError``。
    """
    if expected_count is not None and (not isinstance(expected_count, int) or expected_count <= 0):
        raise SourceValidationError("源程序 PDF 的期望页数必须为正整数。")
    expected_texts = None
    if expected_pages is not None:
        expected_texts = [_comparison_text("".join(rows)) for rows in expected_pages]
        if not expected_texts or any(not text for text in expected_texts):
            raise SourceValidationError("用于核对 PDF 的源程序 HTML 含空白页或没有源码页。")
        if expected_count is not None and expected_count != len(expected_texts):
            raise SourceValidationError("源程序 HTML 页数与期望 PDF 页数不一致。")

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SourceValidationError("校验源程序 PDF 需要 pypdf，请安装 requirements.txt 后重试。") from exc

    try:
        with Path(path).open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted:
                raise SourceValidationError("源程序 PDF 已加密，不能核对源码内容。")
            count = len(reader.pages)
            if count == 0:
                raise SourceValidationError("源程序 PDF 没有页面。")
            wanted = len(expected_texts) if expected_texts is not None else expected_count
            if wanted is not None and count != wanted:
                raise SourceValidationError(f"源程序 PDF 页数不一致：实际 {count} 页，期望 {wanted} 页。")
            for number, page in enumerate(reader.pages, 1):
                content = page.extract_text() or ""
                body_lines = [line for line in content.splitlines() if _compact(line)]
                while body_lines and _is_margin_line(body_lines[0], number, header):
                    body_lines = body_lines[1:]
                while body_lines and _is_margin_line(body_lines[-1], number, header):
                    body_lines = body_lines[:-1]
                if _is_blank_source(content) or not body_lines:
                    raise SourceValidationError(f"源程序 PDF 第 {number} 页为空白或只有页码（含页眉）。")
                if require_page_numbers:
                    lines = [line.strip() for line in content.splitlines() if line.strip()]
                    if not any(_is_margin_line(line, number, header) for line in (lines[0], lines[-1])):
                        raise SourceValidationError(f"源程序 PDF 第 {number} 页缺少正确页码"
                                                    + ("或页眉" if header else "") + "。")
                if expected_texts is not None and expected_texts[number - 1] not in _page_text_candidates(content, number, header):
                    raise SourceValidationError(f"源程序 PDF 第 {number} 页与 HTML 源码不一致，可能存在截断或内容缺失。")
    except SourceValidationError:
        raise
    except Exception as exc:
        raise SourceValidationError(f"无法读取源程序 PDF（{Path(path).name}）：{exc}") from exc
    return {"pages": count, "nonblank_pages": count}
