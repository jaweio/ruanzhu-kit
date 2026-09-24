import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from artifact_manifest import (build_manifest, formal_material_paths,
                               verify_records)  # noqa: E402
from output_names import manual_pdf_name, source_material_pdf_name, submission_dir  # noqa: E402
import zhusque_check  # noqa: E402


class ArtifactManifestTests(unittest.TestCase):
    def test_manifest_binds_endpoint_and_upload_roles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = {
                "id": "01-ai",
                "name": "AI 协作系统（服务端）",
                "short_name": "AI 协作",
                "artifact_label": "后端",
                "version": "V1.0",
                "source_pages": 60,
            }
            project_dir = root / project["id"]
            final = submission_dir(project_dir)
            final.mkdir(parents=True)
            (final / source_material_pdf_name(project)).write_bytes(b"source")
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            with (final / manual_pdf_name(project)).open("wb") as fh:
                writer.write(fh)
            form_dir = project_dir / "auto-fill"
            form_dir.mkdir()
            (form_dir / "config.json").write_text(json.dumps({
                "step4_features": {
                    "programPdf": f"../提交材料/{source_material_pdf_name(project)}",
                    "docPdf": f"../提交材料/{manual_pdf_name(project)}",
                }
            }), encoding="utf-8")
            (project_dir / "朱雀检测报告.md").write_text("# 朱雀检测报告\n风险比例：0%\n", encoding="utf-8")
            zhusque_files = zhusque_check.iter_files([str(project_dir)])
            (project_dir / ".zhusque-final.json").write_text(json.dumps({
                "manifest": zhusque_check.final_manifest(
                    zhusque_files, zhusque_check.DEFAULT_BASE_URL,
                    zhusque_check.DEFAULT_MODEL, zhusque_check.DEFAULT_CHUNK_CHARS,
                ),
                "report": str(project_dir / "朱雀检测报告.md"),
                "base_url": zhusque_check.DEFAULT_BASE_URL,
                "model": zhusque_check.DEFAULT_MODEL,
                "max_chars": zhusque_check.DEFAULT_CHUNK_CHARS,
                "risk_ratio": 0,
            }), encoding="utf-8")
            manifest = build_manifest(Path(td) / "ruanzhu.config.json", {}, project, root)
            self.assertEqual(manifest["materials"]["programPdf"]["filename"], "AI 协作-后端源码.pdf")
            self.assertEqual(manifest["materials"]["docPdf"]["filename"], "AI 协作-后端软件说明.pdf")
            self.assertEqual(manifest["checks"], [])
            self.assertTrue(manifest["ready_for_upload"])
            self.assertEqual(manifest["scope"]["submission"], ["programPdf", "docPdf"])

    def test_manifest_blocks_upload_until_zhusque_gate_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = {"id": "01-ai", "name": "AI 协作系统", "version": "V1.0", "source_pages": 60}
            project_dir = root / project["id"]
            final = submission_dir(project_dir)
            final.mkdir(parents=True)
            (final / source_material_pdf_name(project)).write_bytes(b"source")
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            with (final / manual_pdf_name(project)).open("wb") as fh:
                writer.write(fh)
            form_dir = project_dir / "auto-fill"
            form_dir.mkdir()
            (form_dir / "config.json").write_text(json.dumps({
                "step4_features": {
                    "programPdf": f"../提交材料/{source_material_pdf_name(project)}",
                    "docPdf": f"../提交材料/{manual_pdf_name(project)}",
                }
            }), encoding="utf-8")
            manifest = build_manifest(Path(td) / "ruanzhu.config.json", {}, project, root)
            self.assertFalse(manifest["ready_for_upload"])
            self.assertTrue(any("朱雀正式检测" in item for item in manifest["checks"]))

            # 一次拒绝不够；用户第二次明确拒绝后才记为豁免放行，且不冒充已检测
            import zhusque_check
            args = lambda reason: type("A", (), {"target": str(project_dir), "reason": reason,
                                                 "source": "test", "user_declined": True})()
            self.assertEqual(zhusque_check.decline(args("不想上传")), 0)
            manifest = build_manifest(Path(td) / "ruanzhu.config.json", {}, project, root)
            self.assertFalse(manifest["ready_for_upload"])
            self.assertEqual(zhusque_check.decline(args("再次拒绝")), 0)
            manifest = build_manifest(Path(td) / "ruanzhu.config.json", {}, project, root)
            self.assertFalse(any("朱雀" in item for item in manifest["checks"]))
            self.assertTrue(manifest["zhusque"]["waived"])
            self.assertFalse(manifest["zhusque"]["checked"])

    def test_formal_paths_resolve_output_root_relative_records(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "01-ai"
            (project_dir / "提交材料").mkdir(parents=True)
            source = project_dir / "提交材料" / "AI-后端源码.pdf"
            doc = project_dir / "提交材料" / "AI-后端软件说明.pdf"
            source.write_bytes(b"source")
            doc.write_bytes(b"doc")
            manifest = {
                "_schema": "ruanzhu-kit.material-manifest.v1",
                "materials": {
                    "programPdf": {"path": "01-ai/提交材料/AI-后端源码.pdf"},
                    "docPdf": {"path": "01-ai/提交材料/AI-后端软件说明.pdf"},
                },
            }
            (project_dir / "材料上传清单.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            paths = formal_material_paths(project_dir)
            self.assertEqual(paths["programPdf"], source)
            self.assertEqual(paths["docPdf"], doc)

    def test_verify_rejects_mismatched_form_filename(self):
        files = {
            "programPdf": {"exists": True, "filename": "AI 协作-后端源码.pdf", "pages": 60, "expected_pages": 60},
            "docPdf": {"exists": True, "filename": "AI 协作-后端软件说明.pdf", "pages": 25, "expected_pages": 1},
        }
        errors = verify_records(files, {
            "programPdf": "../提交材料/旧版源码.pdf",
            "docPdf": "../提交材料/AI 协作-后端软件说明.pdf",
        })
        self.assertTrue(any("programPdf 配置文件名不一致" in error for error in errors))

    def _doc_files(self):
        return {
            "programPdf": {"exists": True, "filename": "a源码.pdf", "pages": 60, "expected_pages": 60},
            "docPdf": {"exists": True, "filename": "a软件说明.pdf", "pages": 25, "expected_pages": 1},
        }, {"programPdf": "../提交材料/a源码.pdf", "docPdf": "../提交材料/a软件说明.pdf"}

    def test_verify_rejects_manual_pdf_with_placeholders(self):
        files, form = self._doc_files()
        with patch("artifact_manifest.pdf_text", return_value="功能说明\n【截图预留：订单管理】"):
            errors = verify_records(files, form, Path("a软件说明.pdf"))
        self.assertTrue(any("草稿占位符" in e and "截图预留" in e for e in errors))

    def test_verify_fails_closed_when_manual_pdf_unreadable(self):
        files, form = self._doc_files()
        with patch("artifact_manifest.pdf_text", side_effect=ValueError("broken")):
            errors = verify_records(files, form, Path("a软件说明.pdf"))
        self.assertTrue(any("无法抽取文本" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
