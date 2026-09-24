import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import jev_check


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class JevCheckTests(unittest.TestCase):
    def test_upload_must_be_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "allow-upload"):
                jev_check.evaluate_material(Path(directory))

    def test_gate_uses_conservative_thresholds(self):
        response = {"answers": {
            "ui_interaction": {"noul": 0.96},
            "engineering_readiness": {"noul": 0.95},
            "needs_human_review": {"noul": 0.04},
        }}
        result = jev_check.gate_result(response)
        self.assertTrue(result["passed"])
        response["answers"]["needs_human_review"]["noul"] = 0.06
        self.assertFalse(jev_check.gate_result(response)["passed"])

    def test_compact_excerpt_removes_code_blocks_and_bounds_text(self):
        text = "# 说明\n\n```go\npassword = 'secret'\n```\n" + ("真实步骤。" * 1000)
        excerpt = jev_check._compact_excerpt(text, 100)
        self.assertNotIn("password", excerpt)
        self.assertLessEqual(len(excerpt), 130)

    def test_state_contains_only_compact_local_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            material = Path(directory)
            (material / "软件说明书.md").write_text("真实操作", encoding="utf-8")
            state = jev_check.build_state(
                material,
                {"name": "协作系统", "artifact_label": "后端"},
                local_checks={"metrics": {"截图": 3}, "aigc": {"score": 18}, "issue_counts": {"high": 0}},
            )
            self.assertNotIn("manual_excerpt", state)
        self.assertEqual(state["local_checks"]["metrics"]["截图"], 3)
        self.assertEqual(state["local_checks"]["aigc"]["score"], 18)

    def test_request_sends_typed_questions_and_bearer_key(self):
        payload = {"model": "jev-1", "answers": {}}
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(payload)

        with patch.object(jev_check.urllib.request, "urlopen", fake_urlopen):
            result = jev_check._request({"manual_excerpt": "事实"}, "secret-key", model="jev-1")
        body = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(result, payload)
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(body["model"], "jev-1")
        self.assertEqual(set(body["questions"]), {"ui_interaction", "engineering_readiness", "needs_human_review"})

    def test_cache_does_not_repeat_same_state(self):
        response = {"model": "jev-latest", "answers": {
            "ui_interaction": {"noul": 0.98},
            "engineering_readiness": {"noul": 0.97},
            "needs_human_review": {"noul": 0.01},
        }}
        with tempfile.TemporaryDirectory() as directory:
            material = Path(directory) / "材料"
            material.mkdir()
            (material / "软件说明书.md").write_text("真实操作步骤", encoding="utf-8")
            calls = []
            with patch.dict(os.environ, {"TYPESAFE_API_KEY": "x" * 24, "RUANZHU_JEV_CACHE_DIR": directory}), \
                 patch.object(jev_check, "_request", side_effect=lambda *args, **kwargs: calls.append(1) or response):
                first = jev_check.evaluate_material(material, allow_upload=True)
                second = jev_check.evaluate_material(material, allow_upload=True)
        self.assertTrue(first["gate"]["passed"])
        self.assertTrue(second["cached"])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
