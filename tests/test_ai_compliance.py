import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from ai_compliance import (ASSETS, FOLDER, RECORD, decision, filename, generate,
                           options, paragraphs, print_pdf, supplemental_status)
from artifact_manifest import build_manifest
from aigc_check import collect
from output_names import submission_dir


class AIComplianceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = {"id": "desktop", "name": "协作台（桌面端）", "version": "V2.3",
                        "tech_feature_tag": "人工智能软件"}
        self.cfg = {"copyright_holder": "甲方公司", "output_root": str(self.root),
                    "projects": [self.project]}

    def text(self, path):
        with ZipFile(path) as z:
            parts = [ET.fromstring(z.read(p)) for p in ("word/document.xml", "word/footer1.xml")]
        return "\n".join("".join(p.itertext()) for p in parts)

    def test_ai_tag_automatic_and_multiple_tags(self):
        self.assertTrue(decision({}, self.project)[0])
        for tags in (["应用软件", "人工智能软件"], "应用软件、人工智能软件"):
            self.assertTrue(decision({}, {"tech_feature_tag": tags})[0])

    def test_generic_smart_names_do_not_trigger(self):
        for name in ("智能账单管理系统", "Mail 软件", "AI 协作软件"):
            self.assertFalse(decision({}, {"name": name, "tech_feature_tag": "应用软件"})[0])

    def test_explicit_enable_disable_and_inheritance(self):
        self.assertTrue(decision({"ai_compliance": "always"}, {})[0])
        self.assertFalse(decision({"ai_compliance": "always"}, {"ai_compliance": False})[0])
        self.assertFalse(decision({}, dict(self.project, ai_software=False))[0])
        self.assertTrue(decision({}, {"ai_software": True})[0])
        self.assertTrue(decision({}, {"ai_compliance": "never"}, "always")[0])
        for invalid in ("sometimes", {"mode": None}, 0):
            with self.assertRaises(ValueError):
                decision({"ai_compliance": invalid}, {})
        with self.assertRaises(ValueError):
            decision({}, {"ai_software": "false"})

    def test_non_ai_is_noop(self):
        self.project["tech_feature_tag"] = "应用软件"
        self.assertFalse(generate(self.root, self.cfg, self.project)["enabled"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_docx_and_html_have_current_identity_only(self):
        result = generate(self.root, self.cfg, self.project)
        directory = Path(result["directory"])
        text = self.text(directory / result["docx"])
        for expected in (self.project["name"], "V2.3", "甲方公司", "单位公章", "年"):
            self.assertIn(expected, text)
        for stale in ("厦门益搭", "服务端", "2026", "{{", "核心代码与模型具有原创性"):
            self.assertNotIn(stale, text)
        self.assertEqual(result["missing"], ["签署日期"])
        self.assertFalse(result["signed"])
        self.assertFalse(result["pdf_generated"])
        self.assertNotIn("<script>", (directory / filename(self.project, "html")).read_text())

    def test_template_preserves_geometry_styles_and_relations(self):
        result = generate(self.root, self.cfg, self.project)
        path = Path(result["directory"]) / result["docx"]
        with ZipFile(ASSETS / "ai-compliance-template.docx") as src, ZipFile(path) as dst:
            for name in src.namelist():
                if name not in ("word/document.xml", "word/footer1.xml"):
                    self.assertEqual(src.read(name), dst.read(name), name)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            geometry = lambda z: ET.tostring(ET.fromstring(z.read("word/document.xml")).find("w:body/w:sectPr", ns))
            self.assertEqual(geometry(src), geometry(dst))

    def test_template_contains_no_private_reference_identity(self):
        with ZipFile(ASSETS / "ai-compliance-template.docx") as src:
            contents = "\n".join(src.read(n).decode("utf-8") for n in src.namelist() if n.endswith(".xml"))
        for value in ("厦门益搭", "益搭AI协作", "2026    "):
            self.assertNotIn(value, contents)

    def test_project_holder_overrides_global_and_unknown_facts_are_blank(self):
        self.cfg["copyright_holder"] = "待确认（申请人提供著作权人全称）"
        text, missing = paragraphs(self.cfg, self.project, options(self.cfg, self.project))
        self.assertEqual(text["p07"], "著作权人：")
        self.assertIn("著作权人", missing)
        self.assertNotIn("待确认", "".join(text.values()))
        self.project["copyright_holder"] = "乙方"
        self.assertEqual(paragraphs(self.cfg, self.project, options(self.cfg, self.project))[0]["p07"], "著作权人：乙方")

    def test_dates_are_explicit_not_today_or_completion_date(self):
        self.cfg["development_completed_date"] = "2026-09-22"
        self.assertNotIn("2026", paragraphs(self.cfg, self.project, options(self.cfg, self.project))[0]["date"])
        self.cfg["ai_compliance"] = {"declaration_date": "2026-09-23"}
        self.assertIn("2026 年 09 月 23 日", paragraphs(self.cfg, self.project, options(self.cfg, self.project))[0]["date"])
        for invalid in ("2026-02-30", "tomorrow", "20260923"):
            with self.assertRaises(ValueError):
                paragraphs({}, self.project, {"declaration_date": invalid})

    def test_xml_html_escaping_and_path_sanitization(self):
        self.project["name"] = 'AI <桌面> & "协作" / 程序'
        result = generate(self.root, self.cfg, self.project)
        path = Path(result["directory"]) / result["docx"]
        self.assertIn(self.project["name"], self.text(path))
        html = path.with_suffix(".html").read_text()
        self.assertIn("&lt;桌面&gt;", html)
        self.assertNotIn("/", path.name)

    def test_endpoint_names_do_not_cross_contaminate(self):
        desktop = generate(self.root, self.cfg, self.project)
        backend = dict(self.project, id="server", name="协作台（服务端）")
        server = generate(self.root, self.cfg, backend)
        self.assertNotEqual(desktop["docx"], server["docx"])
        self.assertNotIn("桌面端", self.text(Path(server["directory"]) / server["docx"]))

    def test_stale_pdf_moves_to_history_after_identity_change(self):
        result = generate(self.root, self.cfg, self.project)
        directory = Path(result["directory"])
        pdf = submission_dir(self.root / self.project["id"]) / result["pdf"]
        pdf.write_bytes(b"prior document")
        self.project["version"] = "V3.0"
        generate(self.root, self.cfg, self.project)
        self.assertFalse(pdf.exists())
        self.assertEqual(len(list((directory / "历史").glob("*.pdf"))), 1)
        self.assertFalse(supplemental_status(self.root, self.cfg, self.project)["pdf_current"])

    def test_failure_does_not_mark_old_pdf_as_fresh(self):
        result = generate(self.root, self.cfg, self.project)
        directory = Path(result["directory"])
        (submission_dir(self.root / self.project["id"]) / result["pdf"]).write_bytes(b"old file")
        with patch("render_pdfs.CHROME", "/missing/chrome"), patch("ai_compliance.print_pdf", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                generate(self.root, self.cfg, self.project, pdf=True)
        self.assertFalse(json.loads((directory / RECORD).read_text())["pdf_generated"])
        again = generate(self.root, self.cfg, self.project)
        self.assertFalse(again["pdf_generated"])
        self.assertFalse(supplemental_status(self.root, self.cfg, self.project)["pdf_current"])

    def test_supplement_does_not_replace_two_required_upload_slots(self):
        generate(self.root, self.cfg, self.project)
        manifest = build_manifest(self.root / "config.json", self.cfg, self.project, self.root)
        self.assertEqual(set(manifest["materials"]), {"programPdf", "docPdf"})
        self.assertEqual(manifest["scope"]["submission"], ["programPdf", "docPdf"])
        status = manifest["supplemental"]["aiCompliance"]
        self.assertTrue(status["enabled"])
        self.assertFalse(status["auto_upload"])
        self.assertFalse(status["pdf_current"])

    def test_declaration_excluded_from_automatic_style_rewrite(self):
        result = generate(self.root, self.cfg, self.project)
        (Path(result["directory"]) / "声明.md").write_text("声明正文")
        self.assertEqual(collect([self.root]), [])

    def test_generate_docs_cli_automatically_creates_declaration(self):
        config = self.root / "config.json"
        config.write_text(json.dumps(self.cfg, ensure_ascii=False))
        result = subprocess.run([sys.executable, str(SCRIPTS / "generate_docs.py"), "--config", str(config), "--skip-aigc"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / self.project["id"] / FOLDER / filename(self.project, "docx")).exists())

    def test_printer_finishes_when_pdf_exists_even_if_process_stays_alive(self):
        target = self.root / "printed.pdf"
        command = [sys.executable, "-c",
                   "import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_bytes(b'%PDF-1.4\\n%%EOF');time.sleep(60)", str(target)]
        print_pdf(command, target)
        self.assertTrue(target.read_bytes().endswith(b"%%EOF"))

    def test_printer_exit_without_pdf_is_an_error(self):
        with self.assertRaises(RuntimeError):
            print_pdf([sys.executable, "-c", "raise SystemExit(2)"], self.root / "missing.pdf")

    def test_cli_opt_in_non_ai_and_project_filter(self):
        self.project["tech_feature_tag"] = "应用软件"
        config = self.root / "config.json"
        config.write_text(json.dumps(self.cfg, ensure_ascii=False))
        result = subprocess.run([sys.executable, str(SCRIPTS / "ai_compliance.py"), "--config", str(config),
                                 "--project", "desktop", "--mode", "always"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["enabled"])
        invalid = subprocess.run([sys.executable, str(SCRIPTS / "ai_compliance.py"), "--config", str(config),
                                  "--project", "missing"], capture_output=True, text=True)
        self.assertNotEqual(invalid.returncode, 0)


if __name__ == "__main__":
    unittest.main()
