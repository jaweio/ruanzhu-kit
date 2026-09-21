import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_preview


class SourcePreviewTests(unittest.TestCase):
    def test_collect_project_reports_trimmed_go_material(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "main.go").write_text(
                'package main\nimport (\n "fmt"\n)\n// remove this\nfunc main() { // remove this too\n fmt.Println("业务记录")\n}\n',
                encoding="utf-8",
            )
            project = {"id": "01-demo", "name": "业务系统", "source_files": ["main.go"],
                       "source_pages": 1, "lines_per_page": 5, "scrub_open_source": False}
            result = source_preview.collect_project(repo, project, [], sample_lines=20)
            summary = result["summary"]
            self.assertEqual(summary["included_files"], 1)
            self.assertGreater(summary["comments"], 0)
            self.assertEqual(summary["imports"], 3)
            sample = "\n".join(result["files"][0]["sample"])
            self.assertIn("package main", sample)
            self.assertIn("fmt.Println", sample)
            self.assertNotIn('import (', sample)
            self.assertNotIn("remove this", sample)

    def test_write_preview_is_local_html_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("import os\n# comment\ndef run():\n    return 'ok'\n", encoding="utf-8")
            config = {"copyright_holder": "本地团队", "projects": [{"id": "01-app", "name": "应用", "source_files": ["app.py"]}]}
            html_path = root / "preview.html"
            json_path = root / "preview.json"
            source_preview.write_preview(config, "config.json", root, html_path, json_path=json_path)
            self.assertIn("源程序鉴别材料预览", html_path.read_text(encoding="utf-8"))
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["projects"][0]["summary"]["imports"], 1)


if __name__ == "__main__":
    unittest.main()
