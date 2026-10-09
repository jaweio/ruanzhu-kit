import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import screenshots


class ScreenshotTests(unittest.TestCase):
    def test_backend_evidence_title_omits_internal_id(self):
        self.assertEqual(screenshots.shot_title("01_api-success_能力查询", "", "api-success"), "能力查询")
        self.assertEqual(screenshots.shot_title("05_runtime-log_启动状态", "", "runtime-log"), "启动状态")

    def test_validate_manifest_reports_missing_module_and_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "截图").mkdir()
            (root / "截图" / "7-1.png").write_bytes(b"valid screenshot bytes")
            (root / "截图清单.json").write_text(json.dumps({"items": [
                {"no": "图 7-1", "file": "截图/7-1.png", "module": "订单管理"},
                {"no": "图 7-2", "file": "截图/missing.png", "module": "库存管理"},
            ]}, ensure_ascii=False), encoding="utf-8")
            spec = root / "说明书素材.json"
            spec.write_text(json.dumps({"pages": [{"module": "订单管理"}, {"module": "库存管理"}, {"module": "报表"}]}, ensure_ascii=False), encoding="utf-8")
            report = screenshots.validate_manifest(root, spec)
            self.assertFalse(report["ok"])
            self.assertIn("截图/missing.png", report["missing_files"])
            self.assertEqual(report["missing_modules"], ["报表"])

    def test_validate_manifest_accepts_complete_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "截图").mkdir()
            (root / "截图" / "7-1.png").write_bytes(b"valid screenshot bytes")
            (root / "截图清单.json").write_text(json.dumps({"items": [
                {"no": "图 7-1", "file": "截图/7-1.png", "module": "订单管理"},
            ]}, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(screenshots.validate_manifest(root, None)["ok"])

    def test_backend_evidence_is_checked_when_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "截图").mkdir()
            (root / "截图" / "api-success.png").write_bytes(b"ok")
            (root / "截图清单.json").write_text(json.dumps({"items": [
                {"no": "图 7-1", "file": "截图/api-success.png", "module": "", "evidence_id": "api-success"},
            ]}, ensure_ascii=False), encoding="utf-8")
            spec = root / "说明书素材.json"
            spec.write_text(json.dumps({"pages": [], "evidence_plan": [
                {"id": "api-success", "required": True},
                {"id": "api-error", "required": True},
            ]}, ensure_ascii=False), encoding="utf-8")
            report = screenshots.validate_manifest(root, spec)
            self.assertEqual(report["missing_evidence"], ["api-error"])
            self.assertFalse(report["ok"])

    def test_backend_evidence_needs_no_page_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "截图").mkdir()
            for name, evidence_id in (("7-1.png", "api-success"), ("7-2.png", "api-error"), ("7-3.png", "runtime-log")):
                (root / "截图" / name).write_bytes(b"valid screenshot bytes")
            (root / "截图清单.json").write_text(json.dumps({"items": [
                {"no": f"图 7-{index}", "file": f"截图/7-{index}.png", "module": "", "evidence_id": evidence_id}
                for index, evidence_id in enumerate(("api-success", "api-error", "runtime-log"), 1)
            ]}, ensure_ascii=False), encoding="utf-8")
            spec = root / "说明书素材.json"
            spec.write_text(json.dumps({"pages": [], "evidence_plan": [
                {"id": evidence_id, "required": True}
                for evidence_id in ("api-success", "api-error", "runtime-log")
            ]}, ensure_ascii=False), encoding="utf-8")
            report = screenshots.validate_manifest(root, spec)
            self.assertTrue(report["ok"])
            self.assertEqual(report["unmatched_items"], [])


if __name__ == "__main__":
    unittest.main()
