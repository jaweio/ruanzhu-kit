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


class SourcePageFillTests(unittest.TestCase):
    def test_rows_fill_the_page_and_at_least_50_lines(self):
        from source_material_render import page_metrics, page_lines, PAGE_BODY_HEIGHT_PT
        for per_page in (30, 50, 60, 90):
            project = {"lines_per_page": per_page}
            n = page_lines(project)
            self.assertGreaterEqual(n, 50)
            row, font = page_metrics(project, ["x" * 80])
            self.assertAlmostEqual(row * n, PAGE_BODY_HEIGHT_PT, delta=1.0)  # 从上排到下，不留半页空白
            self.assertLessEqual(font, row)

    def test_long_lines_wrap_without_losing_code(self):
        from source_material_render import wrap_rows, page_metrics, _measurer, PAGE_BODY_WIDTH_PT
        font = page_metrics({})[1]
        long_line = "const result = " + " + ".join(f"value{i}" for i in range(60))
        rows = wrap_rows(["short", long_line], font)
        self.assertGreater(len(rows), 2)                                 # 长行折成多行
        self.assertEqual("".join(rows[1:]).replace(" ", ""), long_line.replace(" ", ""))  # 一字不丢
        width = _measurer(font)
        self.assertTrue(all(width(r) <= PAGE_BODY_WIDTH_PT for r in rows))  # 每行都在页宽内

    def test_reference_typography(self):
        from source_material_render import page_metrics
        row, font = page_metrics({})
        self.assertEqual((row, font), (14.5, 10.5))                     # 五号字、行距 14.5pt、每页 50 行

    def test_blank_lines_removed_by_default(self):
        import inspect, source_material_render
        self.assertIn('get("max_blank_lines", 0)', inspect.getsource(source_material_render.collect_source_material))


class SourcePageNumberTests(unittest.TestCase):
    def test_source_pdf_has_top_right_page_number(self):
        from source_material_render import build_source_html
        html = build_source_html({"name": "演示软件"}, ["a", "b"], 1, 50)
        self.assertIn("@top-right {{ content: counter(page);".replace("{{", "{"), html)


if __name__ == "__main__":
    unittest.main()
