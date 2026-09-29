#!/usr/bin/env python3
"""源码文件解码：识别 UTF-8 / UTF-16 / GBK(GB18030)，无法可靠解码的文件报告为“编码有问题”。

以前统一按 UTF-8 读并忽略错误，GBK 文件的中文会被悄悄丢掉或变成乱码进入材料。
这里只接受能完整解码、且解码后没有替换字符和大量控制字符的文本。
"""

import codecs
from pathlib import Path


class SourceEncodingError(ValueError):
    """文件是二进制或编码无法可靠识别，不能作为源程序材料。"""


_BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
         (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))


def _looks_utf16(data):
    """没有 BOM 的 UTF-16：ASCII 为主的文本每隔一个字节是 0。"""
    if len(data) < 4:
        return None
    sample = data[:4000]
    even = sample[0::2].count(0) / max(1, len(sample[0::2]))
    odd = sample[1::2].count(0) / max(1, len(sample[1::2]))
    if odd > 0.3 and even < 0.05:
        return "utf-16-le"
    if even > 0.3 and odd < 0.05:
        return "utf-16-be"
    return None


def _clean(text):
    """解码结果必须像文本：没有替换字符，控制字符（制表、换行等除外）不超过 1%。"""
    if "�" in text:
        return False
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r\f\v")
    return controls <= max(2, len(text) // 100)


def decode_bytes(data):
    """返回 (text, encoding)；无法可靠解码时抛出 SourceEncodingError。"""
    if not data:
        return "", "utf-8"
    for bom, name in _BOMS:
        if data.startswith(bom):
            try:
                text = data.decode(name)
            except UnicodeDecodeError as exc:
                raise SourceEncodingError(f"带 {name} 标记但内容无法解码") from exc
            if _clean(text):
                return text, name
            raise SourceEncodingError(f"{name} 解码后含异常字符")
    utf16 = _looks_utf16(data)
    if utf16:
        try:
            text = data.decode(utf16)
        except UnicodeDecodeError:
            text = None
        if text is not None and _clean(text):
            return text, utf16
    if b"\x00" in data:
        raise SourceEncodingError("含空字节，疑似二进制文件")
    for name in ("utf-8", "gb18030"):
        try:
            text = data.decode(name)
        except UnicodeDecodeError:
            continue
        if _clean(text):
            return text, name
    raise SourceEncodingError("不是 UTF-8、UTF-16 或 GBK/GB18030 编码，解码会产生乱码")


def read_source(path):
    """读取源码文件，返回 (text, encoding)；编码有问题时抛出 SourceEncodingError。"""
    return decode_bytes(Path(path).read_bytes())


def read_source_text(path, default=""):
    """统计、扫描等非提交场景使用：编码有问题时返回 default，不中断流程。"""
    try:
        return read_source(path)[0]
    except (OSError, SourceEncodingError):
        return default
