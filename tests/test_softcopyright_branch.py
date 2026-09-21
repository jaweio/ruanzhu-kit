import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import softcopyright_branch


class SoftCopyrightBranchTests(unittest.TestCase):
    def test_branch_name_is_stable(self):
        self.assertEqual(softcopyright_branch.branch_name("AI 协作/后端"), "copyright/ai-协作-后端")
        self.assertEqual(softcopyright_branch.branch_name("copyright/demo"), "copyright/demo")

    def test_overlap_report_finds_shared_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "shared.ts").write_text("export {}", encoding="utf-8")
            config = {
                "repo_root": str(root),
                "projects": [
                    {"id": "a", "source_files": ["src/shared.ts", "src/missing.ts"]},
                    {"id": "b", "source_files": ["src/shared.ts"]},
                ],
            }
            report = softcopyright_branch.overlap_report(config)
            self.assertIn("src/shared.ts", report["overlaps"])
            self.assertEqual(report["missing"][0]["file"], "src/missing.ts")


if __name__ == "__main__":
    unittest.main()
