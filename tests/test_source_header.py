import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_material_render import build_source_html, source_page_boxes  # noqa: E402
import source_validation as sv  # noqa: E402

PROJECT = {"name": "星游游戏盒子软件", "version": "V1.0"}


class SourceHeaderTests(unittest.TestCase):
    def test_html_has_top_left_header_and_top_right_page_number(self):
        html = build_source_html(PROJECT, ["const a = 1"], 1, 50)
        self.assertIn('@top-left { content: "星游游戏盒子软件 V1.0"; font-size: 9pt;', html)
        self.assertIn("@top-right { content: counter(page); font-size: 9pt;", html)

    def test_header_quotes_are_escaped(self):
        self.assertIn(r'content: "A\"B V2"', source_page_boxes({"name": 'A"B', "version": "V2"}))

    def test_margin_line_accepts_header_plus_number_and_radicals(self):
        header = "星游游戏盒子软件 V1.0"
        self.assertTrue(sv._is_margin_line("星游游戏盒⼦软件 V1.0 7", 7, header))  # “⼦”为部首字符
        self.assertFalse(sv._is_margin_line("星游游戏盒子软件 V1.0 8", 7, header))  # 页码不对
        self.assertFalse(sv._is_margin_line("其他软件 V1.0 7", 7, header))           # 页眉不对
        self.assertTrue(sv._is_margin_line("7", 7, header))


@unittest.skipIf(sv is None, "")
class SourceHeaderPdfTests(unittest.TestCase):
    def test_header_only_page_is_blank(self):
        try:
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest("未安装 reportlab（可选依赖）")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "s.pdf"
            c = canvas.Canvas(str(path))
            c.drawString(50, 800, "Demo V1.0 1")
            c.save()
            with self.assertRaises(sv.SourceValidationError):
                sv.validate_source_pdf(path, expected_count=1, require_page_numbers=True, header="Demo V1.0")


if __name__ == "__main__":
    unittest.main()
