import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from reportlab.pdfgen import canvas
except ImportError:  # 可选依赖，未安装时跳过本文件
    canvas = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_pdfs
from output_names import source_material_html_name, source_material_pdf_name


@unittest.skipIf(canvas is None, "未安装 reportlab（可选依赖）")
class SourceRenderGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(render_pdfs, "pages", return_value=1))
        self.enterContext(patch.object(render_pdfs, "CHROME", "test-chrome"))
        self.root = Path(self.temp.name)
        self.project = {"id": "demo", "name": "Demo", "source_pages": 60,
                        "source_files": ["main.js"], "scrub_open_source": False}
        self.source_dir = self.root / "demo" / "源程序提取"
        self.source_dir.mkdir(parents=True)
        self.html = self.source_dir / source_material_html_name(self.project)
        self.pdf = self.root / "demo" / "提交材料" / source_material_pdf_name(self.project)
        self.pdf.parent.mkdir()
        self.pdf.write_bytes(b"previous verified submission")
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "main.js").write_text("const answer = 42;\n")

    def write_html(self, text):
        self.html.write_text('<section class="source-page"><div class="source-line">'
                             + text + '</div></section>')

    def printer(self, text):
        def run(html, output, work, expected, header=None):
            pdf = canvas.Canvas(str(output))
            pdf.drawString(550, 820, "1")
            if text:
                pdf.drawString(40, 760, text)
            pdf.showPage()
            pdf.save()
            return render_pdfs.validate_source_pdf(output, expected_pages=expected)
        return run

    def test_blank_cached_html_rejected_before_printing(self):
        self.write_html("&nbsp;")
        with patch.object(render_pdfs, "print_source_pdf") as run:
            with self.assertRaises(ValueError):
                render_pdfs.render_source_pdf(self.root, self.project, {})
        run.assert_not_called()
        self.assertEqual(self.pdf.read_bytes(), b"previous verified submission")

    def test_repo_rebuilds_existing_html_and_records_actual_pages(self):
        self.write_html("const obsolete = 1;")
        with patch.object(render_pdfs, "print_source_pdf", side_effect=self.printer("const answer = 42;")):
            render_pdfs.render_source_pdf(self.root, self.project, {}, self.repo)
        self.assertIn("const answer = 42;", self.html.read_text())
        self.assertNotIn("obsolete", self.html.read_text())
        self.assertTrue(self.pdf.read_bytes().startswith(b"%PDF"))
        record = json.loads((self.source_dir / "源程序取材记录.json").read_text())
        self.assertEqual(record["pages"], 1)
        self.assertTrue(record["complete"])

    def test_cached_legacy_html_gets_page_numbers_without_changing_source(self):
        self.write_html("const answer = 42;")
        before = render_pdfs.parse_source_html(self.html.read_text())
        def print_numbered(html, output, work, expected, header=None):
            self.assertIn("@top-right", html.read_text())
            return self.printer("const answer = 42;")(html, output, work, expected)
        with patch.object(render_pdfs, "print_source_pdf", side_effect=print_numbered):
            render_pdfs.render_source_pdf(self.root, self.project, {})
        self.assertEqual(render_pdfs.parse_source_html(self.html.read_text()), before)
        numbered = self.html.read_text()
        self.assertEqual(render_pdfs.ensure_source_page_numbers(numbered, self.project), numbered)

    def test_old_counter_style_is_upgraded_to_legible_arabic_numbers(self):
        legacy = '''<html><head><style>@page { size: A4; margin: 6.5mm 10mm; }</style>
<style id="ruanzhu-source-page-numbers">@page { @top-right { content: counter(page); font-size: 9pt; } }</style>
</head><body>source</body></html>'''
        numbered = render_pdfs.ensure_source_page_numbers(legacy)
        self.assertEqual(numbered.count('id="ruanzhu-source-page-numbers"'), 1)
        self.assertIn("@top-right { content: counter(page); font-size: 9pt;", numbered)
        self.assertIn("margin-top: 12mm", numbered)
        self.assertIn("content: counter(page)", numbered)
        self.assertNotIn("counter(pages)", numbered)
        self.assertEqual(render_pdfs.ensure_source_page_numbers(numbered), numbered)

    def test_blank_print_preserves_previous_pdf_and_html(self):
        self.write_html("const previous = 1;")
        before = self.html.read_bytes()
        with patch.object(render_pdfs, "print_source_pdf", side_effect=self.printer("")):
            with self.assertRaises(ValueError):
                render_pdfs.render_source_pdf(self.root, self.project, {}, self.repo)
        self.assertEqual(self.pdf.read_bytes(), b"previous verified submission")
        self.assertEqual(self.html.read_bytes(), before)

    def test_truncated_print_is_rejected(self):
        self.write_html("const answer = 42;")
        with patch.object(render_pdfs, "print_source_pdf", side_effect=self.printer("const answer")):
            with self.assertRaises(ValueError):
                render_pdfs.render_source_pdf(self.root, self.project, {})
        self.assertEqual(self.pdf.read_bytes(), b"previous verified submission")

    def test_missing_source_does_not_replace_previous_files(self):
        self.write_html("const previous = 1;")
        before = self.html.read_bytes()
        with patch.object(render_pdfs, "print_source_pdf") as run:
            with self.assertRaises(ValueError):
                render_pdfs.render_source_pdf(self.root, self.project, {}, self.root / "wrong-root")
        run.assert_not_called()
        self.assertEqual(self.html.read_bytes(), before)
        self.assertEqual(self.pdf.read_bytes(), b"previous verified submission")

    def test_completed_pdf_closes_owned_browser_even_if_chrome_stays_alive(self):
        self.write_html("const answer = 42;")
        output = self.root / "printed.pdf"
        self.printer("const answer = 42;")(self.html, output, self.root, [["const answer = 42;"]])
        with patch.object(render_pdfs.subprocess, "Popen") as start:
            process = start.return_value
            process.poll.return_value = None
            result = render_pdfs.print_source_pdf(self.html, output, self.root, [["const answer = 42;"]])
        self.assertEqual(result["pages"], 1)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_browser_exit_without_complete_pdf_fails(self):
        self.write_html("const answer = 42;")
        output = self.root / "printed.pdf"
        with patch.object(render_pdfs.subprocess, "Popen") as start:
            start.return_value.poll.return_value = 1
            with self.assertRaises(ValueError):
                render_pdfs.print_source_pdf(self.html, output, self.root, [["const answer = 42;"]])


if __name__ == "__main__":
    unittest.main()
