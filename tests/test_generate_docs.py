import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_docs
import render_pdfs


class GenerateDocsTests(unittest.TestCase):
    def test_default_chapters_can_be_extended(self):
        project = {
            "id": "01-复杂系统",
            "name": "复杂系统",
            "extra_chapters": [{
                "title": "数据治理",
                "intro": "说明数据生命周期。",
                "sections": [{"title": "数据归档", "content": "按照业务状态归档记录。"}],
            }],
        }
        names = generate_docs.chapter_names(project)
        self.assertEqual(len(names), 11)
        text = generate_docs.manual(project, {}, shots={})
        self.assertIn("# 11 数据治理", text)
        self.assertIn("## 11.1 数据归档", text)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_docs.write_project(root, {}, project)
            self.assertTrue((root / "01-复杂系统" / "说明书章节" / "11-数据治理.md").exists())

    def test_generation_does_not_require_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = {"id": "01-离线生成", "name": "离线生成"}
            generate_docs.write_project(root, {}, project)
            self.assertTrue((root / "01-离线生成" / "软件说明书.md").exists())
            self.assertTrue((root / "01-离线生成" / "说明书章节" / "10-附录.md").exists())

    def test_missing_facts_are_not_filled_with_generic_runtime_claims(self):
        text = generate_docs.manual({"id": "p", "name": "P"}, {})
        self.assertNotIn("双核及以上", text)
        self.assertNotIn("软件应记录启动、配置、核心操作", text)
        self.assertIn("待核验", text)

    def test_pdf_chapter_list_reads_extended_markdown_headings(self):
        markdown = "# 目录\n\n# 软件概述\n正文\n# 附录\n正文\n# 11 数据治理\n正文\n"
        self.assertEqual(render_pdfs.chapter_titles(markdown), ["软件概述", "附录", "数据治理"])
        html = render_pdfs.anchor_h1(
            "<h1>11 数据治理</h1>", "复杂系统", "reference"
        )
        self.assertIn("01-数据治理", html)


if __name__ == "__main__":
    unittest.main()
