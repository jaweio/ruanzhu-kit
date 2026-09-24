import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_pdfs  # noqa: E402
from aigc_rules import find_placeholders  # noqa: E402
from output_names import manual_pdf_name, submission_dir  # noqa: E402


class PlaceholderRuleTests(unittest.TestCase):
    def test_detects_all_draft_markers(self):
        text = "【待核验：日志路径】\n【截图预留：订单管理】\n【待补充】\n按项目实际填写\n【占位图】"
        self.assertEqual(len(find_placeholders(text)), 5)

    def test_ui_labels_are_not_placeholders(self):
        self.assertEqual(find_placeholders("点击【保存】后进入【订单列表】页面"), [])


class RenderGateTests(unittest.TestCase):
    PROJECT = {"id": "01-a", "name": "订单管理系统", "short_name": "订单", "artifact_label": "网页端"}

    def test_refuses_to_render_manual_with_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / self.PROJECT["id"]
            d.mkdir()
            submission_dir(d).mkdir()
            (d / "软件说明书.md").write_text("# 功能模块\n\n【截图预留：订单管理】\n", encoding="utf-8")
            stale = submission_dir(d) / manual_pdf_name(self.PROJECT)
            stale.write_bytes(b"%PDF-old")
            with patch.object(render_pdfs, "run") as run:
                with self.assertRaises(render_pdfs.PlaceholderError) as ctx:
                    render_pdfs.render_software_pdf(root, self.PROJECT, "reference")
            run.assert_not_called()
            self.assertIn("软件说明书.md:3", str(ctx.exception))
            self.assertFalse(stale.exists(), "旧提交件必须作废，避免被上传")
            self.assertTrue((stale.parent / (stale.stem + "-含占位符作废.pdf")).exists())


if __name__ == "__main__":
    unittest.main()
