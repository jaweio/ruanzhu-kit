#!/usr/bin/env python3
"""统一软著交付文件名，按软件简称和端类型生成可定位的交付件名称。"""

import re
from pathlib import Path


# The files that are actually uploaded to the copyright centre belong together.
# Keep editable source/HTML inputs in their production folders, but put every
# final PDF in this one directory so a file picker cannot accidentally select
# an old or intermediate artifact.
SUBMISSION_DIR = "提交材料"

# A manual is easiest to review when it stays close to forty pages. This is
# a review target, not a request to add blank pages or repeat text: projects
# with less verified material should stay shorter and receive a warning.
MANUAL_PAGE_TARGET = 40
MANUAL_PAGE_TOLERANCE = 5


def manual_page_window(project=None, config=None):
    """Return ``(minimum, maximum, target)`` for a software manual."""
    project = project or {}
    config = config or {}
    target = project.get("manual_page_target", config.get("manual_page_target", MANUAL_PAGE_TARGET))
    tolerance = project.get("manual_page_tolerance", config.get("manual_page_tolerance", MANUAL_PAGE_TOLERANCE))
    try:
        target = int(target)
        tolerance = int(tolerance)
    except (TypeError, ValueError):
        target, tolerance = MANUAL_PAGE_TARGET, MANUAL_PAGE_TOLERANCE
    target = max(1, target)
    tolerance = max(0, min(tolerance, target - 1))
    return target - tolerance, target + tolerance, target


def submission_dir(project_dir):
    """Return the single directory containing final uploadable PDFs."""
    return Path(project_dir) / SUBMISSION_DIR


def submission_path(project_dir, filename):
    """Return a final-material path below :data:`SUBMISSION_DIR`."""
    return submission_dir(project_dir) / filename


def submission_form_path(filename):
    """Path from ``<project>/auto-fill/config.json`` to a final PDF."""
    return f"../{SUBMISSION_DIR}/{filename}"


def display_stem(project):
    """返回适合文件名的软件前缀；未配置简称时回退到软件全称。"""
    raw = str(project.get("artifact_prefix") or project.get("output_name") or
              project.get("short_name") or project.get("name") or "软件").strip()
    safe = re.sub(r'[\\/:*?"<>|]+', "-", raw).strip(" .")
    return safe or "软件"


def endpoint_label(project):
    """返回材料所属端类型，优先使用配置，缺省时从 document_kind 推断。"""
    explicit = project.get("artifact_label") or project.get("endpoint_label")
    if explicit:
        return re.sub(r'[\\/:*?"<>|]+', "-", str(explicit).strip()).strip(" .")
    kind = str(project.get("document_kind") or "").strip().lower()
    labels = {
        "backend": "后端", "api": "后端", "server": "后端", "service": "服务端",
        "desktop": "桌面端", "pc": "桌面端", "electron": "桌面端",
        "mobile": "移动端", "ios": "移动端", "android": "移动端",
        "web": "网页端", "frontend": "网页端", "miniprogram": "小程序", "wechat": "小程序",
    }
    return labels.get(kind, "")


def artifact_stem(project):
    label = endpoint_label(project)
    return f"{display_stem(project)}-{label}" if label else display_stem(project)


def manual_pdf_name(project):
    return f"{artifact_stem(project)}软件说明.pdf"


def manual_html_name(project):
    return f"{artifact_stem(project)}软件说明.html"


def source_material_stem(project, pages):
    # pages 保留在函数签名中，兼容旧调用；页数在报告和 PDF 元数据中记录，
    # 文件名只保留软件和端类型，便于浏览器按“后端/桌面端/移动端”定位。
    return f"{artifact_stem(project)}源码"


def source_material_pdf_name(project):
    return f"{source_material_stem(project, None)}.pdf"


def source_material_html_name(project):
    return f"{source_material_stem(project, None)}.html"


def source_material_docx_name(project):
    return f"{source_material_stem(project, None)}.docx"
