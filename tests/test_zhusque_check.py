import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import zhusque_check


class ZhusqueCheckTests(unittest.TestCase):
    def test_parse_json_and_code_fence(self):
        result = zhusque_check.parse_result(
            "```json\n{" + '"overall_score": 62, "level": "高", "issues": []' + "}\n```"
        )
        self.assertEqual(result["overall_score"], 62)
        self.assertEqual(result["level"], "高")

    def test_parse_invalid_response_is_safe(self):
        result = zhusque_check.parse_result("服务暂时不可用")
        self.assertIsNone(result["overall_score"])
        self.assertEqual(result["issues"], [])

    def test_chunks_are_bounded(self):
        pieces = zhusque_check.chunks("abcdefghij", 3)
        self.assertEqual(pieces, ["abc", "def", "ghi", "j"])

    def test_normalized_fingerprint_ignores_whitespace_only_changes(self):
        first = zhusque_check.text_fingerprint("功能一\n\n功能二")
        second = zhusque_check.text_fingerprint("功能一  功能二")
        self.assertEqual(first, second)

    def test_cache_round_trip_does_not_store_source_text(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            key = zhusque_check.cache_key("https://example.test/v1", "model", 12000, "敏感正文")
            result = {"overall_score": 12, "level": "低", "summary": "", "issues": []}
            zhusque_check.save_cached_result(cache_dir, key, result)
            self.assertEqual(zhusque_check.load_cached_result(cache_dir, key), result)
            self.assertNotIn("敏感正文", (cache_dir / f"{key}.json").read_text(encoding="utf-8"))

    def test_directory_collection_skips_internal_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "软件说明书.md").write_text("正文", encoding="utf-8")
            (root / "AIGC检测报告.md").write_text("不应上传", encoding="utf-8")
            (root / "说明书章节").mkdir()
            (root / "说明书章节" / "01.md").write_text("不应重复上传", encoding="utf-8")
            files = zhusque_check.iter_files([str(root)])
            self.assertEqual([p.name for p in files], ["软件说明书.md"])

    def test_missing_key_does_not_contact_network(self):
        with patch.dict(zhusque_check.os.environ, {}, clear=True), patch.object(zhusque_check, "keychain_get", return_value=None):
            self.assertIsNone(zhusque_check.resolve_key()[0])


if __name__ == "__main__":
    unittest.main()
