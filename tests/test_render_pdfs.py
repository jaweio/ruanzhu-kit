import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_pdfs  # noqa: E402


class ScreenshotLayoutTests(unittest.TestCase):
    def test_every_style_prints_software_identity_left_and_page_number_right(self):
        for style in render_pdfs.STYLE_CHOICES:
            html = render_pdfs.html_doc("订单管理系统", "<p>正文</p>", version="V1.0",
                                        style=style, chapters=["软件概述"])
            self.assertIn('@top-left { content: "订单管理系统 V1.0";', html, style)
            self.assertIn('@top-right { content: counter(page);', html, style)
            self.assertNotIn('content: "订单管理系统 V1.0" counter(page)', html, style)
            self.assertNotIn("page-break-before:always", html, style)
            self.assertNotIn("@bottom", html, style)

    def test_every_style_prints_software_version_on_cover(self):
        for style in render_pdfs.STYLE_CHOICES:
            html = render_pdfs.html_doc(
                "订单管理系统", "<p>正文</p>", version="V1.0",
                style=style, chapters=["软件概述"],
            )
            self.assertIn('<div class="doc-kind">软件说明书 · V1.0</div>', html, style)

    def test_only_requested_chapters_start_new_pages(self):
        html = render_pdfs.html_doc(
            "Example", "<h1>第一章</h1><h1>第二章</h1>",
            chapters=["第一章", "第二章"], chapter_page_breaks=["第二章"],
        )
        self.assertIn('#chapter-2 { break-before: page; page-break-before: always; }', html)
        self.assertNotIn('#chapter-1 { break-before: page;', html)

    def test_manual_uses_a4_paper_in_every_style(self):
        for style in render_pdfs.STYLE_CHOICES:
            html = render_pdfs.html_doc("订单管理系统", "<p>正文</p>", style=style, chapters=["软件概述"])
            self.assertIn("size: A4", html, style)
            self.assertNotIn("Letter", html, style)

    def test_screenshot_and_caption_are_wrapped_in_one_figure(self):
        html = (
            '<p><img src="截图/7-7.png" alt="图 7-7 收件箱" /></p>\n'
            '<p>图 7-7　收件箱与通知</p>'
        )

        grouped = render_pdfs.group_screenshot_figures(html)

        self.assertEqual(grouped.count('<figure class="screenshot-figure">'), 1)
        self.assertIn('<figcaption>图 7-7　收件箱与通知</figcaption>', grouped)
        self.assertNotIn('</p>\n<p>图 7-7', grouped)

    def test_image_without_caption_is_also_non_breaking(self):
        html = '<p><img src="截图/01-首页.png" alt="首页" /></p>'

        grouped = render_pdfs.group_screenshot_figures(html)

        self.assertEqual(grouped, '<figure class="screenshot-figure"><img src="截图/01-首页.png" alt="首页" /></figure>')

    def test_html_doc_emits_non_breaking_screenshot_css(self):
        html = render_pdfs.html_doc(
            "订单管理系统",
            '<p><img src="截图/01-首页.png" alt="图 7-1 首页" /></p>',
            style="reference",
            chapters=["功能模块"],
        )

        self.assertIn("figure.screenshot-figure", html)
        self.assertIn("page-break-inside: avoid", html)
        self.assertIn("break-inside: avoid", html)
        self.assertIn('<figure class="screenshot-figure">', html)

    def test_manual_layout_allows_short_final_page_but_not_middle_page(self):
        def sample(path, sparse_middle=False):
            doc = pymupdf.open()
            for index in range(3 if sparse_middle else 2):
                page = doc.new_page()
                page.insert_text((60, 30), "Example V1.0", fontsize=9)
                page.insert_text((520, 30), str(index + 1), fontsize=9)
                page.insert_text((60, 80), "real body", fontsize=12)
                if index == 0 or (sparse_middle and index == 2):
                    page.insert_text((60, 510), "real body continued", fontsize=12)
                elif not sparse_middle:
                    page.insert_text((60, 250), "final page continued", fontsize=12)
            doc.save(path)
            doc.close()

        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "manual.pdf"
            sample(pdf)
            self.assertEqual(render_pdfs.validate_manual_pdf_layout(pdf, "Example", "V1.0")["pages"], 2)
            pdf.unlink()
            sample(pdf, sparse_middle=True)
            with self.assertRaisesRegex(render_pdfs.ManualLayoutError, "第 2 页正文"):
                render_pdfs.validate_manual_pdf_layout(pdf, "Example", "V1.0")

    def test_manual_layout_rejects_missing_page_number_on_right(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "manual.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((40, 30), "Example V1.0", fontsize=9)
            page.insert_text((60, 80), "body", fontsize=12)
            doc.save(pdf)
            doc.close()
            with self.assertRaisesRegex(render_pdfs.ManualLayoutError, "右上角"):
                render_pdfs.validate_manual_pdf_layout(pdf, "Example", "V1.0")

    def test_manual_layout_rejects_extra_title_on_right(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "manual.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((40, 30), "Example V1.0", fontsize=9)
            page.insert_text((400, 30), "Example", fontsize=9)
            page.insert_text((520, 30), "1", fontsize=9)
            page.insert_text((60, 80), "body", fontsize=12)
            page.insert_text((60, 300), "body continued", fontsize=12)
            doc.save(pdf)
            doc.close()
            with self.assertRaisesRegex(render_pdfs.ManualLayoutError, "右上角"):
                render_pdfs.validate_manual_pdf_layout(pdf, "Example", "V1.0")

    def test_manual_layout_rejects_missing_project_name_and_three_line_orphan(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "manual.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((520, 30), "1", fontsize=9)
            page.insert_text((60, 80), "first page", fontsize=12)
            page.insert_text((60, 510), "first page continued", fontsize=12)
            last = doc.new_page()
            last.insert_text((60, 30), "Example V1.0", fontsize=9)
            last.insert_text((520, 30), "2", fontsize=9)
            for n in range(3):
                last.insert_text((60, 80 + n * 20), f"last page {n}", fontsize=12)
            doc.save(pdf)
            doc.close()
            with self.assertRaisesRegex(render_pdfs.ManualLayoutError, "第 1 页左上角"):
                render_pdfs.validate_manual_pdf_layout(pdf, "Example", "V1.0")
            doc = pymupdf.open(pdf)
            doc[0].insert_text((60, 30), "Example V1.0", fontsize=9)
            doc.saveIncr()
            doc.close()
            with self.assertRaisesRegex(render_pdfs.ManualLayoutError, "末页仅占"):
                render_pdfs.validate_manual_pdf_layout(pdf, "Example", "V1.0")

    def test_failed_layout_does_not_replace_existing_submission_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = {"id": "p", "name": "Example", "version": "V1.0"}
            folder = root / "p"
            folder.mkdir()
            (folder / "软件说明书.md").write_text("# 软件概述\n\n正文。", encoding="utf-8")
            old_pdf = render_pdfs.submission_dir(folder) / render_pdfs.manual_pdf_name(project)
            old_pdf.parent.mkdir(parents=True)
            old_pdf.write_bytes(b"previous submission")

            def print_sparse(command, **_kwargs):
                target = Path(next(part.split("=", 1)[1] for part in command if part.startswith("--print-to-pdf=")))
                doc = pymupdf.open()
                page = doc.new_page()
                page.insert_text((60, 80), "body without header")
                doc.save(target)
                doc.close()

            with patch.object(render_pdfs, "CHROME", "fake-chrome"), \
                 patch.object(render_pdfs, "md_to_html", return_value="<h1>软件概述</h1><p>正文</p>"), \
                 patch.object(render_pdfs, "run", side_effect=print_sparse):
                with self.assertRaises(render_pdfs.ManualLayoutError):
                    render_pdfs.render_software_pdf(root, project, "reference")
            self.assertEqual(old_pdf.read_bytes(), b"previous submission")


if __name__ == "__main__":
    unittest.main()
