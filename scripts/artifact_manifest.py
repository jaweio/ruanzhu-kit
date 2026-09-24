#!/usr/bin/env python3
"""生成并核对软著上传材料清单。

材料清单把“哪一份软件、哪个端、哪个字段、哪个文件”绑定在一起，
用于浏览器上传前人工核对，不能替代网页确认页回读。

用法：
  python3 artifact_manifest.py --config <ruanzhu.config.json> --project <id>
  python3 artifact_manifest.py --config <ruanzhu.config.json> --project <id> --verify --strict
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from aigc_rules import find_placeholders, pdf_text
from ai_compliance import FOLDER as AI_FOLDER, RECORD as AI_RECORD, filename as ai_filename, supplemental_status
from output_names import (endpoint_label, manual_pdf_name,
                          source_material_pdf_name, submission_dir,
                          submission_form_path)


def load_material_manifest(path):
    """读取正式材料清单；坏清单返回 None，让调用方使用兼容回退。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("_schema", "").split(".v")[0] != "ruanzhu-kit.material-manifest":
        return None
    materials = data.get("materials")
    if not isinstance(materials, dict) or not all(isinstance(v, dict) for v in materials.values()):
        return None
    return data


def resolve_manifest_path(manifest_path, record_path):
    """解析清单中的相对路径，兼容 v1 的 output_root 相对路径和项目相对路径。"""
    raw = Path(str(record_path))
    if raw.is_absolute():
        return raw
    # absolute() 保留 macOS /var 与 /private/var 的用户路径形式，避免后续
    # relative_to 失配；清单解析不需要跟随符号链接。
    manifest_path = Path(manifest_path).absolute()
    candidates = [
        manifest_path.parent / raw,
        manifest_path.parent.parent / raw,
        manifest_path.parent.parent.parent / raw,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # 返回最常见的项目根相对路径，供“缺失”提示使用
    return candidates[0]


def formal_material_paths(project_dir):
    """返回正式上传材料路径及角色，未生成清单时返回空字典。"""
    manifest_path = Path(project_dir) / "材料上传清单.json"
    manifest = load_material_manifest(manifest_path)
    if not manifest:
        return {}
    result = {}
    for key, record in manifest.get("materials", {}).items():
        path = record.get("path")
        if path:
            result[key] = resolve_manifest_path(manifest_path, path)
    return result


def _resolve_root(config_path, cfg, project_id):
    raw = Path(cfg.get("output_root", "soft-copyright-materials"))
    if raw.is_absolute():
        return raw
    # 相对 output_root 以配置文件所在目录为优先，避免当前工作目录恰好
    # 也有一个同名 soft-copyright-materials 时把清单写到错误项目。
    candidates = [config_path.parent / raw, config_path.parent, Path.cwd() / raw]
    for candidate in candidates:
        if (candidate / project_id).exists():
            return candidate
    return candidates[0]


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pdf_pages(path):
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        try:
            out = subprocess.run([pdfinfo, str(path)], check=True, text=True,
                                 capture_output=True).stdout
            match = re.search(r"^Pages:\s+(\d+)", out, re.M)
            if match:
                return int(match.group(1))
        except (OSError, subprocess.CalledProcessError):
            pass
    data = path.read_bytes()
    pages = re.findall(rb"/Type\s*/Page[^s]", data)
    if pages:
        return len(pages)
    match = re.search(rb"/Count\s+(\d+)", data)
    return int(match.group(1)) if match else None


def _file_record(path, root, label, expected_pages=None):
    exists = path.is_file()
    record = {
        "label": label,
        "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        "filename": path.name,
        "exists": exists,
        "expected_pages": expected_pages,
        "pages": _pdf_pages(path) if exists and path.suffix.lower() == ".pdf" else None,
        "bytes": path.stat().st_size if exists else 0,
        "sha256": _sha256(path) if exists else None,
    }
    return record


def _project(cfg, project_id):
    for project in cfg.get("projects", []):
        if project.get("id") == project_id:
            return project
    raise SystemExit(f"找不到项目：{project_id}")


def _zhusque_status(project_dir):
    """只认与当前材料目录绑定的最终指纹和报告。"""
    marker = Path(project_dir) / ".zhusque-final.json"
    report = Path(project_dir) / "朱雀检测报告.md"
    from zhusque_check import decline_status
    declined = decline_status(project_dir)
    base = {"checked": False, "marker": str(marker), "report": str(report),
            "waived": declined["waived"], "declines": declined["count"],
            "decline_threshold": declined["threshold"]}
    if not marker.is_file() or not report.is_file():
        return base
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    recorded_report = Path(str(data.get("report", ""))).expanduser()
    report_match = recorded_report.name == report.name or recorded_report.resolve() == report.resolve()
    content_match = False
    try:
        # Recompute the same text-only fingerprint used by zhusque_check.
        # Import lazily to avoid making the manifest tool depend on the
        # detector during module import and to keep the two workflows aligned.
        from zhusque_check import final_manifest, iter_files
        files = iter_files([str(project_dir)])
        content_match = bool(files) and data.get("manifest") == final_manifest(
            files,
            str(data.get("base_url", "https://ai-gateway.edgeone.link/v1")),
            str(data.get("model", "@makers/zhuque-text")),
            int(data.get("max_chars", 12000)),
        )
    except (OSError, ValueError, TypeError, ImportError, RuntimeError):
        content_match = False
    return {
        **base,
        "checked": bool(data.get("manifest")) and report_match and content_match,
        "completed_at": data.get("completed_at", ""),
        "risk_ratio": data.get("risk_ratio"),
        "content_match": content_match,
    }


def build_manifest(config_path, cfg, project, root):
    project_dir = root / project["id"]
    final_dir = submission_dir(project_dir)
    # Prefer the unified final-material directory.  The fallback keeps old
    # projects readable until they are regenerated/migrated.
    source_pdf = final_dir / source_material_pdf_name(project)
    if not source_pdf.exists():
        source_pdf = project_dir / "源程序提取" / source_material_pdf_name(project)
    manual_pdf = final_dir / manual_pdf_name(project)
    if not manual_pdf.exists():
        manual_pdf = project_dir / manual_pdf_name(project)
    form_path = project_dir / "auto-fill" / "config.json"
    form = json.loads(form_path.read_text(encoding="utf-8")) if form_path.exists() else {}
    features = form.get("step4_features", {}) if isinstance(form, dict) else {}
    files = {
        "programPdf": _file_record(source_pdf, root, "程序鉴别材料",
                                    int(project.get("source_pages", 60))),
        "docPdf": _file_record(manual_pdf, root, "文档鉴别材料", 1),
    }
    checks = verify_records(files, features, manual_pdf)
    zhusque = _zhusque_status(project_dir)
    if not zhusque["checked"] and not zhusque["waived"]:
        checks.append("尚未完成当前正文的朱雀正式检测（必需）；运行 zhusque_check.py finalize。"
                      f"用户明确拒绝已记录 {zhusque['declines']} 次，满 {zhusque['decline_threshold']} 次才可豁免")
    ai_status = supplemental_status(root, cfg, project)
    if ai_status["enabled"]:
        ai_dir = project_dir / AI_FOLDER
        ai_status["files"] = {
            "docx": _file_record(ai_dir / ai_filename(project, "docx"), root, "AI 合规声明编辑稿"),
            "pdf": _file_record(final_dir / ai_filename(project, "pdf"), root,
                                "AI 合规声明签署模板", 1),
        }
        # Keep the legacy location visible when a project has not yet been
        # migrated; status resolution accepts both locations.
        ai_status["auto_upload"] = False
    return {
        "_schema": "ruanzhu-kit.material-manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": str(config_path),
        "project_id": project["id"],
        "software_name": project.get("name", project["id"]),
        "short_name": project.get("short_name", ""),
        "artifact_label": endpoint_label(project),
        "version": project.get("version", "V1.0"),
        "materials": files,
        "supplemental": {"aiCompliance": ai_status},
        "zhusque": zhusque,
        "scope": {
            "submission": ["programPdf", "docPdf"],
            "review": [
                f"{project['id']}/软件说明书.md",
                f"{project['id']}/申请表填报文案.md",
                f"{project['id']}/auto-fill/config.json",
            ],
            "internal": [
                f"{project['id']}/{AI_FOLDER}/{AI_RECORD}",
                f"{project['id']}/AIGC检测报告.md",
                f"{project['id']}/版权风险检查报告.md",
                f"{project['id']}/看板.html",
            ],
        },
        "form_paths": {
            "programPdf": (submission_form_path(source_pdf.name)
                           if source_pdf.parent == final_dir else features.get("programPdf", "")),
            "docPdf": (submission_form_path(manual_pdf.name)
                       if manual_pdf.parent == final_dir else features.get("docPdf", "")),
        },
        "checks": checks,
        "ready_for_upload": not checks,
    }


def verify_records(files, form_features, manual_pdf=None):
    errors = []
    for key, record in files.items():
        if not record["exists"]:
            errors.append(f"{key} 文件不存在：{record['path']}")
            continue
        if record["pages"] is not None and record["pages"] < record["expected_pages"]:
            errors.append(f"{key} 页数不足：{record['pages']}/{record['expected_pages']}")
        configured = str(form_features.get(key, ""))
        if not configured:
            errors.append(f"auto-fill/config.json 缺少 {key}")
        elif Path(configured).name != record["filename"]:
            errors.append(f"{key} 配置文件名不一致：{Path(configured).name} ≠ {record['filename']}")
    if manual_pdf is not None and files["docPdf"]["exists"]:
        try:
            hits = find_placeholders(pdf_text(manual_pdf))
        except (Exception, SystemExit) as exc:  # 读不出文本就无法证明干净，按不通过处理
            hits = None
            errors.append(f"docPdf 无法抽取文本，不能确认不含草稿占位符：{exc}")
        if hits:
            errors.append(f"docPdf 含 {len(hits)} 处草稿占位符（如 {hits[0][1]}），不得上传")
    if files["programPdf"]["filename"] == files["docPdf"]["filename"]:
        errors.append("程序鉴别材料和文档鉴别材料不能使用同一个文件")
    return errors


def main():
    parser = argparse.ArgumentParser(description="生成并核对软著浏览器上传材料清单")
    parser.add_argument("--config", required=True, help="ruanzhu.config.json")
    parser.add_argument("--project", help="项目 id；只有一份项目时可省略")
    parser.add_argument("--out", help="材料清单 JSON 输出路径，默认写入项目目录")
    parser.add_argument("--verify", action="store_true", help="核对文件、页数和 auto-fill 路径")
    parser.add_argument("--strict", action="store_true", help="有任何核对问题时退出码为 1")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    projects = cfg.get("projects", [])
    project_id = args.project or (projects[0]["id"] if len(projects) == 1 else None)
    if not project_id:
        raise SystemExit("多份项目时必须指定 --project")
    project = _project(cfg, project_id)
    root = _resolve_root(config_path, cfg, project_id)
    manifest = build_manifest(config_path, cfg, project, root)
    out = Path(args.out).resolve() if args.out else root / project_id / "材料上传清单.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    for key, record in manifest["materials"].items():
        print(f"{key}: {'OK' if record['exists'] else '缺失'} {record['filename']}")
    if manifest["checks"]:
        for error in manifest["checks"]:
            print(f"[high] {error}")
    else:
        print("上传前核对通过：端类型、材料类型、文件名、页数和表单路径一致")
    if args.strict and manifest["checks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
