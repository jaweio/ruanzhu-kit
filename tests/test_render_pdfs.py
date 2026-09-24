import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_pdfs  # noqa: E402


class ScreenshotLayoutTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
