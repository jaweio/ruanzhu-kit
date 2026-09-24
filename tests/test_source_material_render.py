import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_material_render import build_source_html, collect_source_material


class SourceMaterialRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "main.js").write_text(
            'const label = "中文 <标签>";\nfunction run() {\n  return label;\n}\n',
            encoding="utf-8",
        )
        self.project = {
            "name": "示例软件",
            "source_files": ["src/main.js"],
            "source_pages": 2,
            "lines_per_page": 3,
            "source_font_size": 6.5,
            "source_row_height": 8.15,
            "redact": True,
            "scrub_open_source": False,
            "source_material": {"trim_comments": True, "trim_imports": True, "max_blank_lines": 1},
        }

    def test_collect_and_selects_fixed_pages(self):
        result = collect_source_material(self.repo, self.project)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["lines_per_page"], 3)
        self.assertEqual(len(result["selected"]), 6)
        self.assertIn('const label = "中文 <标签>";', result["lines"])

    def test_html_escapes_code_and_has_one_section_per_page(self):
        result = collect_source_material(self.repo, self.project)
        html = build_source_html(self.project, result["selected"], result["pages"], result["lines_per_page"])
        self.assertEqual(html.count('<section class="source-page">'), 2)
        self.assertIn("中文 &lt;标签&gt;", html)
        self.assertNotIn("LibreOffice", html)


if __name__ == "__main__":
    unittest.main()
