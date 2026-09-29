import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_material_render import build_source_html, collect_source_material, write_source_html


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
        # 每页至少 50 行：配置的 3 行被提升为 50，4 行代码只占 1 页
        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["lines_per_page"], 50)
        # 代码只有 4 行（不足 2 页×3 行），按规则全部提交一次，不补空行凑满 6 行
        self.assertEqual(result["selected"], result["lines"])
        self.assertEqual(len(result["selected"]), 4)
        self.assertTrue(result["complete"])
        self.assertIn('const label = "中文 <标签>";', result["lines"])

    def test_html_escapes_code_and_has_one_section_per_page(self):
        result = collect_source_material(self.repo, self.project)
        html = build_source_html(self.project, result["selected"], result["pages"], result["lines_per_page"])
        self.assertEqual(html.count('<section class="source-page">'), 1)
        self.assertIn("中文 &lt;标签&gt;", html)
        self.assertNotIn("LibreOffice", html)

    def test_wrapped_rows_determine_whether_selection_is_complete(self):
        (self.repo / "src/main.js").write_text(
            "\n".join(f"const value{i} = " + "x" * 200 for i in range(40)), encoding="utf-8")
        self.project["source_pages"] = 1
        result = collect_source_material(self.repo, self.project)
        self.assertEqual(len(result["lines"]), 40)
        self.assertEqual(len(result["selected"]), 50)
        self.assertFalse(result["complete"])

    def test_directory_cannot_be_used_as_a_source_file(self):
        self.project["source_files"] = ["src"]
        with self.assertRaises(ValueError) as error:
            collect_source_material(self.repo, self.project)
        self.assertIn(str((self.repo / "src").resolve()), str(error.exception))

    def test_missing_source_file_fails_even_when_other_files_have_code(self):
        self.project["source_files"].append("src/missing.js")
        with self.assertRaises(ValueError) as error:
            collect_source_material(self.repo, self.project)
        message = str(error.exception)
        self.assertIn("--repo", message)
        self.assertIn(str(self.repo.resolve()), message)
        self.assertIn(str((self.repo / "src/missing.js").resolve()), message)

    def test_wrong_repository_reports_every_missing_path(self):
        self.project["source_files"] = ["server/main.js", "server/service.js"]
        with self.assertRaises(ValueError) as error:
            collect_source_material(self.repo, self.project)
        for rel in self.project["source_files"]:
            self.assertIn(str((self.repo / rel).resolve()), str(error.exception))

    def test_empty_or_fully_trimmed_source_is_rejected(self):
        for content in ("", " \n\t\n\u00a0\n", "// only a comment\nimport os\n"):
            with self.subTest(content=content):
                (self.repo / "src/main.js").write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError) as error:
                    collect_source_material(self.repo, self.project)
                self.assertIn(str(self.repo.resolve()), str(error.exception))

    def test_no_configured_sources_is_rejected(self):
        self.project["source_files"] = []
        with self.assertRaisesRegex(ValueError, "source_files"):
            collect_source_material(self.repo, self.project)

    def test_failed_collection_does_not_replace_existing_html(self):
        output = self.repo / "source.html"
        output.write_text("previous valid output", encoding="utf-8")
        self.project["source_files"] = ["missing.js"]
        with self.assertRaises(ValueError):
            write_source_html(self.repo, self.project, output)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous valid output")

    def test_html_rejects_blank_pages_and_inconsistent_page_counts(self):
        cases = [
            ([], 1, 50),
            (["", " \t", "\u00a0"], 1, 50),
            (["code"], 2, 50),
            (["code"] * 51, 1, 50),
            (["code"] * 50 + [" "], 2, 50),
            ([" "] * 50 + ["code"], 2, 50),
            (["code"], 0, 50),
            (["code"], -1, 50),
            (["code"], 1, 0),
            (["code"], 1, -1),
        ]
        for lines, pages, per_page in cases:
            with self.subTest(lines=len(lines), pages=pages, per_page=per_page):
                with self.assertRaises(ValueError):
                    build_source_html(self.project, lines, pages, per_page)


if __name__ == "__main__":
    unittest.main()
