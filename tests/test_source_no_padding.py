import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_material_render import select_source_lines, expected_source_pages  # noqa: E402


class SourceNoPaddingTests(unittest.TestCase):
    def test_short_code_is_submitted_once_without_padding(self):
        lines = [f"line {i}" for i in range(1200)]
        selected, pages, per_page = select_source_lines(lines, {"lines_per_page": 50, "source_pages": 60})
        self.assertEqual(selected, lines)          # 全部代码，顺序不变
        self.assertEqual(len(set(selected)), 1200)  # 没有重复
        self.assertEqual(pages, 24)                 # 1200/50，按实际页数
        self.assertNotIn("", selected)              # 没有补空行

    def test_partial_last_page_rounds_up(self):
        _, pages, _ = select_source_lines(["x"] * 1201, {"lines_per_page": 50, "source_pages": 60})
        self.assertEqual(pages, 25)

    def test_long_code_takes_front_and_back_30_pages(self):
        lines = [f"line {i}" for i in range(5000)]
        selected, pages, _ = select_source_lines(lines, {"lines_per_page": 50, "source_pages": 60})
        self.assertEqual(pages, 60)
        self.assertEqual(selected[:1500], lines[:1500])
        self.assertEqual(selected[1500:], lines[-1500:])
        self.assertEqual(len(set(selected)), 3000)

    def test_expected_pages_follow_selection_record(self):
        with tempfile.TemporaryDirectory() as td:
            project = {"source_pages": 60}
            self.assertEqual(expected_source_pages(td, project), (60, False))
            (Path(td) / "源程序提取").mkdir()
            (Path(td) / "源程序提取" / "源程序取材记录.json").write_text(
                json.dumps({"pages": 24, "complete": True}), encoding="utf-8")
            self.assertEqual(expected_source_pages(td, project), (24, True))


if __name__ == "__main__":
    unittest.main()
