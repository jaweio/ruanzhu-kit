import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import zhusque_check


class ZhusqueCheckTests(unittest.TestCase):
    def test_parse_json_and_code_fence(self):
        result = zhusque_check.parse_result({
            "status": "success",
            "labels_ratio": {"0": 0.4, "1": 0.2, "2": 0.4},
            "segment_labels": [{"label": 2, "conf": 0.8, "order": 1, "position": [0, 2], "text": "机密"}],
        })
        self.assertEqual(result["overall_score"], 60)
        self.assertEqual(result["labels_ratio"]["1"], 0.2)

    def test_parse_invalid_response_is_safe(self):
        with self.assertRaises(ValueError):
            zhusque_check.parse_result("服务暂时不可用")

    def test_request_uses_official_zhuque_classify_endpoint(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return json.dumps({
                    "status": "success",
                    "labels_ratio": {"0": 1, "1": 0, "2": 0},
                    "segment_labels": [],
                }).encode("utf-8")

        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response()

        with patch.object(zhusque_check.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = zhusque_check.request_model(
                "k" * 24, "https://ai-gateway.edgeone.link/v1",
                zhusque_check.DEFAULT_MODEL, "说明书.md", 1, 1, "正文",
            )
        request = captured["request"]
        self.assertIsInstance(request, Request)
        self.assertEqual(request.full_url, "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "k" * 24)
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"text": "正文", "is_merge": False})
        self.assertEqual(result["overall_score"], 0)

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
            result = {"status": "success", "labels_ratio": {"0": 1, "1": 0, "2": 0},
                      "segment_labels": [], "overall_score": 0}
            zhusque_check.save_cached_result(cache_dir, key, result)
            self.assertEqual(zhusque_check.load_cached_result(cache_dir, key), result)
            self.assertNotIn("敏感正文", (cache_dir / f"{key}.json").read_text(encoding="utf-8"))

    def test_cache_rejects_legacy_chat_completion_result(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            key = zhusque_check.cache_key("https://example.test/v1", "model", 12000, "正文")
            zhusque_check.save_cached_result(cache_dir, key, {"overall_score": 12})
            self.assertIsNone(zhusque_check.load_cached_result(cache_dir, key))

    def test_directory_collection_skips_internal_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "软件说明书.md").write_text("正文", encoding="utf-8")
            (root / "AIGC检测报告.md").write_text("不应上传", encoding="utf-8")
            (root / "说明书章节").mkdir()
            (root / "说明书章节" / "01.md").write_text("不应重复上传", encoding="utf-8")
            files = zhusque_check.iter_files([str(root)])
            self.assertEqual([p.name for p in files], ["软件说明书.md"])

    def test_formal_manifest_excludes_legacy_and_source_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "软件说明书.md").write_text("正文", encoding="utf-8")
            (root / "申请表填报文案.md").write_text("申请表", encoding="utf-8")
            (root / "auto-fill").mkdir()
            (root / "auto-fill" / "config.json").write_text("{}", encoding="utf-8")
            (root / "文档.pdf").write_bytes(b"pdf")
            (root / "源程序提取").mkdir()
            (root / "源程序提取" / "源码.pdf").write_bytes(b"source")
            (root / "旧版未裁剪材料").mkdir()
            (root / "旧版未裁剪材料" / "旧.md").write_text("旧内容", encoding="utf-8")
            (root / "材料上传清单.json").write_text(json.dumps({
                "_schema": "ruanzhu-kit.material-manifest.v1",
                "materials": {"programPdf": {"path": "01/源程序提取/源码.pdf"},
                               "docPdf": {"path": "文档.pdf"}},
            }, ensure_ascii=False), encoding="utf-8")
            names = {p.name for p in zhusque_check.iter_files([str(root)])}
            self.assertEqual(names, {"软件说明书.md", "申请表填报文案.md", "config.json", "文档.pdf"})

    def test_missing_key_does_not_contact_network(self):
        with patch.dict(zhusque_check.os.environ, {}, clear=True), patch.object(zhusque_check, "keychain_get", return_value=None):
            self.assertIsNone(zhusque_check.resolve_key()[0])

    def test_decline_requires_explicit_user_flag_and_reason(self):
        with tempfile.TemporaryDirectory() as td:
            make = lambda **kw: type("A", (), {"target": td, "reason": "用户拒绝", "source": "test",
                                               "user_declined": True, **kw})()
            self.assertEqual(zhusque_check.decline(make(user_declined=False)), 2)
            self.assertEqual(zhusque_check.decline(make(reason="  ")), 2)
            self.assertEqual(zhusque_check.decline_status(td)["count"], 0)
            zhusque_check.decline(make())
            self.assertFalse(zhusque_check.decline_status(td)["waived"])
            zhusque_check.decline(make(reason="第二次拒绝"))
            state = zhusque_check.decline_status(td)
            self.assertEqual(state["count"], 2)
            self.assertTrue(state["waived"])

    def test_web_handoff_is_written_without_a_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "软件说明书.md").write_text("正文", encoding="utf-8")
            handoff = zhusque_check.write_web_handoff(root)
            text = (handoff / "网页检测说明.md").read_text(encoding="utf-8")
            self.assertIn(zhusque_check.WEB_URL, text)
            self.assertIn("未配置朱雀 API Key", text)


if __name__ == "__main__":
    unittest.main()
