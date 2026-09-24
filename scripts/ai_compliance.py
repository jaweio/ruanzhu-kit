#!/usr/bin/env python3
"""按项目配置生成生成式人工智能合规声明模板；不签署、不判定合规、不上传。"""

import argparse
from datetime import date
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from aigc_rules import find_placeholders
from output_names import submission_dir

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FOLDER = "补充声明"
RECORD = "AI合规声明生成记录.json"
MODES = ("auto", "always", "never")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def options(cfg, project, mode=None):
    result = {"mode": "auto", "declaration_date": "", "recipient": "国家版权局"}
    for obj in (cfg, project):
        raw = obj.get("ai_compliance", {})
        if isinstance(raw, bool):
            raw = {"mode": "always" if raw else "never"}
        elif isinstance(raw, str):
            raw = {"mode": raw}
        if not isinstance(raw, dict):
            raise ValueError("ai_compliance 必须为对象、模式字符串或布尔值")
        result.update(raw)
    if mode is not None:
        result["mode"] = mode
    if result["mode"] not in MODES:
        raise ValueError("ai_compliance.mode 必须为 auto、always 或 never")
    return result


def decision(cfg, project, mode=None):
    setting = options(cfg, project, mode)["mode"]
    if setting != "auto":
        return setting == "always", f"mode={setting}"
    flag = project.get("ai_software", cfg.get("ai_software"))
    if flag is not None:
        if not isinstance(flag, bool):
            raise ValueError("ai_software 必须为 true 或 false")
        return flag, f"ai_software={str(flag).lower()}"
    tags = project.get("tech_feature_tag", cfg.get("tech_feature_tag", ""))
    if not isinstance(tags, list):
        tags = re.split(r"[,，、;/；|]", str(tags))
    enabled = any(str(tag).strip() == "人工智能软件" for tag in tags)
    return enabled, "技术特点标签为人工智能软件" if enabled else "未标记为人工智能软件"


def fact(value):
    text = str(value or "").strip()
    if find_placeholders(text) or re.search(r"待确认|待填写|待补充|待核验", text):
        return ""
    # Configuration values are plain text; never evaluate instructions or markup.
    return re.sub(r"\s+", " ", text)


def filename(project, suffix):
    # Use the full project name, so desktop/backend declarations cannot share names.
    name = fact(project.get("name")) or "软件"
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name).strip(" .")
    return f"关于符合《生成式人工智能服务管理暂行办法》{safe}.{suffix}"


def paragraphs(cfg, project, opts):
    name = fact(project.get("name"))
    version = fact(project.get("version"))
    holder = fact(project.get("copyright_holder", cfg.get("copyright_holder")))
    recipient = fact(opts.get("recipient")) or "国家版权局"
    values = dict(name=name, version=version, holder=holder, recipient=recipient,
                  software=f"《{name}》" if name else "本软件",
                  declarant=f"声明人{holder}" if holder else "声明人",
                  version_intro=f"（版本号：{version}）" if version else "")
    templates = json.loads((ASSETS / "ai-compliance-content.json").read_text(encoding="utf-8"))
    result = {key: text.format_map(values) for key, text in templates.items()}
    raw_date = fact(opts.get("declaration_date"))
    if raw_date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            raise ValueError("ai_compliance.declaration_date 必须为 YYYY-MM-DD 或留空")
        parsed = date.fromisoformat(raw_date)
        result["date"] = f"日期：{parsed.year} 年 {parsed.month:02d} 月 {parsed.day:02d} 日"
    else:
        result["date"] = "日期：　　　　年　　月　　日"
    missing = [key for key, value in (("软件全称", name), ("版本号", version),
                                      ("著作权人", holder), ("签署日期", raw_date)) if not value]
    return result, missing


def content_fingerprint(text):
    parts = [json.dumps(text, ensure_ascii=False, sort_keys=True).encode(),
             (ASSETS / "ai-compliance-template.docx").read_bytes()]
    return hashlib.sha256(b"\0".join(parts)).hexdigest()


def write_docx(path, text):
    # Only replace verified text slots. All noneditable package parts stay byte-identical.
    with ZipFile(ASSETS / "ai-compliance-template.docx") as source, \
            ZipFile(path, "w", ZIP_DEFLATED) as dest:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename in ("word/document.xml", "word/footer1.xml"):
                xml = data.decode("utf-8")
                for key, value in text.items():
                    xml = xml.replace("{{" + key + "}}", escape(value, quote=False))
                if re.search(r"\{\{[^{}]+\}\}", xml):
                    raise ValueError("声明模板存在未填充插槽")
                data = xml.encode("utf-8")
                ET.fromstring(data)
            dest.writestr(item, data)


def html_document(text):
    sections = []
    for key, value in text.items():
        if key == "date":
            continue
        tag = "h1" if key == "p01" else "h2" if key in {"p04", "p08", "p15", "p17"} else "p"
        cls = "sign" if key == "p20" else "body" if key in {"p03", "p09", "p10", "p11", "p12", "p13", "p14", "p16", "p18"} else ""
        sections.append(f'<{tag} class="{cls}">{escape(value)}</{tag}>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>生成式人工智能合规声明</title>
<style>
@page { size: A4; margin: 25.24mm 30.71mm 25mm 31.49mm; }
* { box-sizing: border-box; }
body { font-family: "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", "Arial Unicode MS", sans-serif;
  color: #000; font-size: 10pt; line-height: 1.55; margin: 0; }
h1 { font-size: 15.5pt; font-weight: 400; line-height: 1.65; margin: 0 0 5mm; }
h2 { font-size: 10pt; font-weight: 700; margin: 4mm 0 2.5mm; break-after: avoid; }
p { margin: 0 0 1.5mm; orphans: 2; widows: 2; }
p.body { text-indent: 2em; text-align: justify; }
.sign { text-align: right; margin-top: 6mm; break-inside: avoid; }
.date { text-align: right; margin-top: 6mm; break-before: avoid; white-space: pre-wrap; }
</style><body>''' + "\n".join(sections) + f'<p class="date">{escape(text["date"])}</p></body></html>'


def read_record(directory):
    try:
        value = json.loads((directory / RECORD).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def print_pdf(command, candidate):
    """Stop only this isolated Chromium group once its PDF has been written.

    Chromium helpers can keep stderr pipes open after the main process exits;
    use a log file and a fresh process group instead of waiting on those pipes.
    """
    with (candidate.parent / "chromium.log").open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log,
                                   start_new_session=os.name != "nt")
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                if candidate.is_file() and candidate.read_bytes().rstrip().endswith(b"%%EOF"):
                    return
                if process.poll() is not None:
                    raise RuntimeError(f"Chromium 未生成完整声明 PDF（退出码 {process.returncode}）")
                time.sleep(0.1)
            raise RuntimeError("Chromium 生成声明 PDF 超时")
        finally:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def generate(root, cfg, project, *, mode=None, pdf=False):
    enabled, reason = decision(cfg, project, mode)
    if not enabled:
        return {"enabled": False, "reason": reason}
    opts = options(cfg, project, mode)
    text, missing = paragraphs(cfg, project, opts)
    project_dir = Path(root) / project["id"]
    directory = project_dir / FOLDER
    final_dir = submission_dir(project_dir)
    directory.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = content_fingerprint(text)
    previous = read_record(directory)
    docx = directory / filename(project, "docx")
    html = directory / filename(project, "html")
    target = final_dir / filename(project, "pdf")
    legacy_target = directory / filename(project, "pdf")
    if not target.exists() and legacy_target.exists():
        # One-time migration for projects generated before final PDFs were
        # consolidated.  Keep the editable DOCX/HTML and record in place.
        legacy_target.replace(target)
    # Move an outdated PDF out of the current selection before writing new inputs.
    if target.exists() and previous.get("input_sha256") != fingerprint:
        archive = directory / "历史"
        archive.mkdir(exist_ok=True)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()[:12]
        target.replace(archive / f"{target.stem}-{digest}.pdf")
    write_docx(docx, text)
    html.write_text(html_document(text), encoding="utf-8")
    record = {"enabled": True, "reason": reason, "mode": opts["mode"],
              "project_id": project["id"], "software_name": fact(project.get("name")),
              "version": fact(project.get("version")), "input_sha256": fingerprint,
              "missing": missing, "status": "需核对并签署", "signed": False,
              "docx": docx.name, "pdf": target.name,
              "pdf_path": str(target.relative_to(project_dir)),
              "pdf_generated": False}
    record_path = directory / RECORD
    # Persist this before invoking Chromium, so failures cannot look like success.
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if pdf:
        # Import lazily to avoid a dependency cycle with the regular PDF workflow.
        from render_pdfs import CHROME
        if not CHROME:
            raise RuntimeError("生成 AI 合规声明 PDF 需要 Chrome/Chromium；DOCX 已生成")
        with tempfile.TemporaryDirectory(prefix="ruanzhu-ai-") as tmp:
            candidate = Path(tmp) / "declaration.pdf"
            command = [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                       "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                       "--disable-background-networking", "--disable-component-update",
                       f"--user-data-dir={Path(tmp) / 'profile'}", f"--print-to-pdf={candidate}",
                       html.resolve().as_uri()]
            print_pdf(command, candidate)
            from pypdf import PdfReader
            pages = PdfReader(candidate).pages
            plain = "".join(p.extract_text() for p in pages)
            if not pages or "责任承诺" not in plain or find_placeholders(plain):
                raise RuntimeError("AI 合规声明 PDF 内容检查失败")
            target.write_bytes(candidate.read_bytes())
    if target.is_file():
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        trusted = (pdf or (previous.get("pdf_generated") is True
                          and previous.get("input_sha256") == fingerprint
                          and previous.get("pdf_sha256") == digest))
        if trusted:
            record["pdf_generated"] = True
            record["pdf_sha256"] = digest
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**record, "directory": str(directory)}


def supplemental_status(root, cfg, project):
    enabled, reason = decision(cfg, project)
    if not enabled:
        return {"enabled": False, "reason": reason}
    directory = Path(root) / project["id"] / FOLDER
    record = read_record(directory)
    text, missing = paragraphs(cfg, project, options(cfg, project))
    project_dir = Path(root) / project["id"]
    pdf = submission_dir(project_dir) / filename(project, "pdf")
    legacy_pdf = directory / filename(project, "pdf")
    if not pdf.exists() and legacy_pdf.exists():
        pdf = legacy_pdf
    current = record.get("input_sha256") == content_fingerprint(text)
    verified_pdf = (current and pdf.is_file() and record.get("pdf_generated") is True
                    and hashlib.sha256(pdf.read_bytes()).hexdigest() == record.get("pdf_sha256"))
    return {"enabled": True, "reason": reason, "current": current, "pdf_current": bool(verified_pdf),
            "missing": missing, "status": "需核对并签署", "signed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--project", help="只生成指定项目；默认处理全部项目")
    parser.add_argument("--mode", choices=MODES, help="本次生成方式，覆盖配置")
    parser.add_argument("--pdf", action="store_true", help="同时生成 PDF（需要 Chrome/Chromium）")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    projects = [p for p in cfg.get("projects", []) if not args.project or p["id"] == args.project]
    if not projects:
        parser.error("未找到指定项目")
    from artifact_manifest import _resolve_root
    try:
        for project in projects:
            root = _resolve_root(config_path, cfg, project["id"])
            result = generate(root, cfg, project, mode=args.mode, pdf=args.pdf)
            print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"生成失败：{exc}\n")


if __name__ == "__main__":
    main()
