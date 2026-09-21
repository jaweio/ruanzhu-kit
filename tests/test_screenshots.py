import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import screenshots


class ScreenshotTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
