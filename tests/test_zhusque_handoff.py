import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import zhusque_browser
import zhusque_check as z
import zhusque_handoff as handoff
import zhusque_incremental as inc


def detected(text, channel="web"):
    return {"status": "success", "labels_ratio": {"0": 1, "1": 0, "2": 0},
            "segment_labels": [{"label": 0, "position": [0, len(text)]}], "channel": channel,
            "evidence": {"text_sha256": hashlib.sha256(text.encode()).hexdigest()}}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="朱雀 CUA ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.doc = self.root / "软件说明书.md"
        self.doc.write_text("原始正文。" * 160 + "\n", encoding="utf-8")
        self.unit = inc.collect_units([self.doc], 2000)[0][0]
        self.args = SimpleNamespace(targets=[str(self.root)], channel="auto", plan=False,
                                    max_risk_ratio=.2, max_chars=2000, allow_upload=True,
                                    no_cache=False, finalize=True, report=None, browser_timeout=10)
        self.profile = self.root / "专用 profile"
        self.key = patch.object(z, "resolve_key", return_value=(None, None)).start()
        self.cache = patch.object(z, "cache_directory", return_value=self.root / "cache").start()
        self.api = patch.object(z, "request_model").start()
        self.browser = patch.object(zhusque_browser, "BrowserDetector").start()
        self.browser.return_value.profile_dir = self.profile
        self.addCleanup(patch.stopall)

    def run_check(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = inc.run(self.args)
        self.output = stream.getvalue()
        return code

    def create(self, reason="captcha", **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return handoff.create_handoff(self.root, self.unit, "manifest", self.args, reason,
                                          profile_dir=self.profile, **kwargs)

    def block(self, reason="captcha"):
        self.browser.return_value.detect.side_effect = zhusque_browser.BrowserDetectionError(
            reason, "测试阻塞", {"page_record": str(self.root / "evidence.json"),
                                 "text_sha256": self.unit["id"], "secret_cookie": "not-recorded"})

    def test_failure_emits_machine_event_with_exact_private_text_and_no_completion(self):
        self.block()
        self.assertEqual(self.run_check(), 2)
        record = handoff.load_active(self.root)
        self.assertEqual(record["status"], "pending_computer_use")
        self.assertEqual(record["text_sha256"], hashlib.sha256(Path(record["text_path"]).read_bytes()).hexdigest())
        self.assertEqual(Path(record["text_path"]).read_text(), self.unit["text"])
        self.assertEqual(os.stat(record["text_path"]).st_mode & 0o777, 0o600)
        self.assertEqual(record["source"]["file"], str(self.doc.resolve()))
        self.assertNotIn("secret_cookie", record["evidence"])
        event = next(line for line in self.output.splitlines() if line.startswith(handoff.EVENT_PREFIX))
        event = json.loads(event[len(handoff.EVENT_PREFIX):])
        self.assertEqual(event["status"], "pending_computer_use")
        self.assertTrue(Path(event["handoff_path"]).is_file())
        self.assertFalse((self.root / z.FINAL_MARKER).exists())

    def test_resume_checks_web_before_api_and_resolves_without_reusing_handoff_as_score(self):
        self.block()
        self.assertEqual(self.run_check(), 2)
        old = handoff.load_active(self.root)
        self.key.return_value = ("unit-test-key", "mock")
        self.browser.return_value.detect.side_effect = lambda text, request_id: {
            **detected(text), "delivery": "resumed"}
        self.assertEqual(self.run_check(), 0)
        self.api.assert_not_called()
        resolved = handoff.load_active(self.root)
        self.assertEqual(resolved["handoff_id"], old["handoff_id"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertTrue(Path(resolved["text_path"]).exists())
        self.assertTrue((self.root / "朱雀复核" / "接管记录" / (old["handoff_id"] + ".json")).exists())
        self.assertTrue((self.root / z.FINAL_MARKER).exists())

    def test_relative_target_handoff_resumes_via_absolute_argv_from_another_directory(self):
        self.block()
        self.args.targets = ["."]
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(self.run_check(), 2)
        finally:
            os.chdir(original_cwd)
        record = handoff.load_active(self.root)
        self.assertEqual(record["source"]["file"], str(self.doc.resolve()))
        self.assertEqual(record["resume_argv"][3], str(self.root.resolve()))
        self.args.targets = [record["resume_argv"][3]]
        self.key.return_value = ("unit-test-key", "mock")
        self.browser.return_value.detect.side_effect = lambda text, request_id: {
            **detected(text), "delivery": "resumed"}
        self.assertEqual(self.run_check(), 0)
        self.api.assert_not_called()
        self.assertEqual(handoff.load_active(self.root)["status"], "resolved")
        self.assertTrue((self.root / z.FINAL_MARKER).exists())

    def test_reconcile_compares_canonical_paths(self):
        self.create()
        alias = self.root / "同一原文.md"
        alias.symlink_to(self.doc)
        row = {**self.unit, "file": str(alias), "result": detected(self.unit["text"])}
        self.assertEqual(handoff.reconcile(self.root, [row], "manifest")["status"], "resolved")

    def test_quota_is_not_computer_use_fallback(self):
        self.block("quota")
        self.assertEqual(self.run_check(), 2)
        self.assertEqual(handoff.load_active(self.root)["status"], "blocked_quota")
        self.assertNotIn(handoff.EVENT_PREFIX, self.output)
        self.assertEqual(self.browser.return_value.detect.call_count, 1)
        self.assertFalse((self.root / z.FINAL_MARKER).exists())

    def test_source_change_invalidates_old_handoff_and_new_unit_is_not_resumed(self):
        self.block()
        self.assertEqual(self.run_check(), 2)
        previous = handoff.load_active(self.root)
        self.doc.write_text(self.doc.read_text().replace("原", "改", 1))
        self.key.return_value = ("unit-test-key", "mock")
        self.api.side_effect = lambda *args: detected(args[-1], "api")
        self.assertEqual(self.run_check(), 0)
        stale = handoff.load_active(self.root)
        self.assertEqual(stale["handoff_id"], previous["handoff_id"])
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(self.api.call_count, 1)
        self.assertEqual(self.browser.return_value.detect.call_count, 1)

    def test_pending_receipt_reference_matches_driver_identity_and_marks_uncertainty(self):
        reference = handoff.receipt_reference(self.root, self.unit, self.profile)
        identity = {"request_id": self.unit["id"], "text_sha256": self.unit["id"],
                    "profile_dir": str(self.profile.resolve()), "url": handoff.WEB_URL, "phase": "uncertain"}
        handoff.save_json(reference["path"], identity)
        record = self.create()
        self.assertTrue(record["pending_receipt"]["identity_matches"])
        self.assertTrue(record["pending_receipt"]["submission_may_have_occurred"])
        self.assertEqual(record["pending_receipt"]["phase"], "uncertain")
        self.assertIn("duplicate_uncertain_submission", record["actions"]["forbidden"])
        identity["text_sha256"] = "0" * 64
        handoff.save_json(reference["path"], identity)
        self.assertFalse(handoff.receipt_reference(self.root, self.unit, self.profile)["identity_matches"])

    def test_resume_arguments_are_argv_and_omit_force_to_avoid_duplicate_submission(self):
        self.args.no_cache = True
        self.args.report = str(self.root / "报告 $(echo injected).md")
        record = self.create()
        argv = record["resume_argv"]
        self.assertIsInstance(argv, list)
        self.assertIn(str(self.root.resolve()), argv)
        self.assertIn(str(Path(self.args.report).resolve()), argv)
        self.assertNotIn("--no-cache", argv)
        self.assertNotIn("--plan", argv)
        self.assertEqual(argv[2], "finalize")

    def test_wrong_text_hash_never_writes_handoff(self):
        self.unit["id"] = "0" * 64
        with self.assertRaises(ValueError):
            self.create()
        self.assertIsNone(handoff.load_active(self.root))

    def test_wrong_web_result_hash_never_resolves_pending_record(self):
        self.create()
        row = {**self.unit, "result": {**detected(self.unit["text"]), "evidence": {"text_sha256": "0" * 64}}}
        self.assertEqual(handoff.reconcile(self.root, [row], "manifest")["status"], "pending_computer_use")
        row["result"] = {"status": "success", "labels_ratio": {"0": 2, "1": 0, "2": 0}}
        self.assertEqual(handoff.reconcile(self.root, [row], "manifest")["status"], "pending_computer_use")

    def test_invalid_handoff_json_does_not_crash_workflow(self):
        path = self.root / "朱雀复核" / handoff.HANDOFF_NAME
        path.parent.mkdir()
        path.write_text('{"version":1,"status":"pending_computer_use"}')
        self.key.return_value = ("unit-test-key", "mock")
        self.api.side_effect = lambda *args: detected(args[-1], "api")
        self.assertEqual(self.run_check(), 0)

    def test_handoff_write_failure_and_driver_cleanup_failure_preserve_partial_state(self):
        self.doc.write_text(self.unit["text"] + "\n\n" + "另一个段落。" * 140)
        self.browser.return_value.detect.side_effect = [detected(self.unit["text"]),
            zhusque_browser.BrowserDetectionError("captcha", "测试验证码")]
        self.browser.return_value.close.side_effect = RuntimeError("模拟清理失败")
        with patch.object(handoff, "create_handoff", side_effect=OSError("模拟磁盘错误")):
            self.assertEqual(self.run_check(), 2)
        state = json.loads((self.root / inc.STATE_NAME).read_text())
        self.assertEqual(state["stats"]["uploaded_units"], 1)
        self.assertEqual(state["stats"]["handoff_error"], "write_failed")
        self.assertFalse(state["summary"]["complete"])
        self.assertEqual(len(list((self.root / "cache").glob("*.json"))), 1)

    def test_plan_does_not_create_cua_handoff_or_launch_browser(self):
        self.args.plan = True
        self.args.allow_upload = False
        self.assertEqual(self.run_check(), 0)
        self.browser.assert_not_called()
        self.assertIsNone(handoff.load_active(self.root))

    def capture(self, **overrides):
        self.block()
        self.assertEqual(self.run_check(), 2)
        record = handoff.load_active(self.root)
        evidence_path = self.root / "live-ax.txt"
        evidence_path.write_text("UNIT TEST live page evidence fixture", encoding="utf-8")
        capture = {"source": "computer_use_live_dom", "url": handoff.WEB_URL,
                   "submitted_text_sha256": record["text_sha256"], "request_id": record["request_id"],
                   "captured_at": handoff.timestamp(), "evidence": {"accessibility_record": str(evidence_path.resolve())},
                   "segments": [{"text": self.unit["text"][:200], "label": 1},
                                {"text": self.unit["text"][200:], "label": 0}]}
        capture.update(overrides)
        path = self.root / "capture.json"
        path.write_text(json.dumps(capture, ensure_ascii=False), encoding="utf-8")
        return path

    def test_cua_import_validates_full_text_computes_ratio_and_requires_finalize(self):
        capture = self.capture()
        imported = handoff.import_cua_result(self.root, capture)
        self.assertEqual(imported["status"], "result_cached")
        self.assertTrue(imported["finalize_required"])
        self.assertFalse((self.root / z.FINAL_MARKER).exists())
        cached = inc.cached_unit(self.unit, self.root / "cache", z.DEFAULT_BASE_URL, z.DEFAULT_MODEL, 2000, "web")
        self.assertAlmostEqual(cached["labels_ratio"]["1"], .25)
        self.assertEqual(cached["segment_labels"][0]["position"], [0, 200])
        self.assertEqual(handoff.load_active(self.root)["status"], "resolved")
        self.assertEqual(self.run_check(), 1)  # Full valid coverage, risk exceeds configured .20.
        self.assertEqual(self.browser.return_value.detect.call_count, 1)
        self.api.assert_not_called()
        self.assertFalse((self.root / z.FINAL_MARKER).exists())

    def test_cua_import_rejects_total_scores_without_classified_text(self):
        capture = self.capture(segments=[], labels_ratio={"0": 1, "1": 0, "2": 0})
        with self.assertRaisesRegex(ValueError, "不接受仅截图占比"):
            handoff.import_cua_result(self.root, capture)
        self.assertFalse((self.root / "cache").exists())
        self.assertEqual(handoff.load_active(self.root)["status"], "pending_computer_use")

    def test_cua_import_cache_write_failure_keeps_handoff_pending(self):
        capture = self.capture()
        with patch.object(z, "save_cached_result", return_value=None):
            with self.assertRaisesRegex(OSError, "未完整写入缓存"):
                handoff.import_cua_result(self.root, capture)
        self.assertEqual(handoff.load_active(self.root)["status"], "pending_computer_use")
        self.assertFalse((self.root / z.FINAL_MARKER).exists())
        self.assertFalse((self.root / "cache").exists())

    def test_cua_import_mismatching_cached_result_does_not_mark_resolved(self):
        capture = self.capture()
        existing = detected(self.unit["text"])
        key = z.cache_key(z.WEB_URL, z.DEFAULT_MODEL, 2000, self.unit["text"])
        z.save_cached_result(self.root / "cache", key, existing)
        with patch.object(z, "save_cached_result", return_value=None):
            with self.assertRaisesRegex(OSError, "未完整写入缓存"):
                handoff.import_cua_result(self.root, capture)
        self.assertEqual(handoff.load_active(self.root)["status"], "pending_computer_use")
        self.assertFalse((self.root / z.FINAL_MARKER).exists())

    def test_cua_import_rejects_wrong_text_shortened_text_and_unknown_labels(self):
        capture = self.capture()
        original = json.loads(capture.read_text())
        variations = [
            {"segments": [{"text": self.unit["text"][:-1], "label": 0}]},
            {"segments": [{"text": self.unit["text"], "label": 3}]},
            {"segments": [{"text": self.unit["text"], "label": True}]},
            {"segments": [{"text": self.unit["text"], "label": 0.0}]},
            {"submitted_text_sha256": "0" * 64},
            {"url": "https://example.com/ai-detect/"},
            {"url": 5}, {"captured_at": "2000-01-01T00:00:00Z"}, {"evidence": {}}]
        for change in variations:
            with self.subTest(change=list(change)):
                capture.write_text(json.dumps({**original, **change}))
                with self.assertRaises(ValueError):
                    handoff.import_cua_result(self.root, capture)
                self.assertFalse((self.root / "cache").exists())

    def test_cua_import_rejects_changed_materials_and_marks_old_record_stale(self):
        capture = self.capture()
        self.doc.write_text(self.doc.read_text().replace("原", "改", 1))
        with self.assertRaisesRegex(ValueError, "材料已变更"):
            handoff.import_cua_result(self.root, capture)
        self.assertEqual(handoff.load_active(self.root)["status"], "stale")
        self.assertFalse((self.root / "cache").exists())

    def test_cua_import_rejects_tampered_pending_text(self):
        capture = self.capture()
        record = handoff.load_active(self.root)
        Path(record["text_path"]).write_text("篡改的文本")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            handoff.import_cua_result(self.root, capture)
        self.assertFalse((self.root / "cache").exists())

    def test_cua_import_accepts_display_whitespace_but_maps_positions_to_original(self):
        self.doc.write_text("甲 乙\n" * 200 + "\n", encoding="utf-8")
        self.unit = inc.collect_units([self.doc], 2000)[0][0]
        capture = self.capture(segments=[{"text": "甲乙" * 20, "label": 1},
                                         {"text": "甲乙" * 180, "label": 0}])
        handoff.import_cua_result(self.root, capture)
        cached = inc.cached_unit(self.unit, self.root / "cache", z.DEFAULT_BASE_URL, z.DEFAULT_MODEL, 2000, "web")
        self.assertAlmostEqual(cached["labels_ratio"]["1"], .1)
        self.assertEqual(cached["segment_labels"][0]["position"], [0, 79])
        self.assertEqual(cached["segment_labels"][1]["position"], [80, 719])
        self.assertEqual(self.run_check(), 0)
        self.assertTrue((self.root / z.FINAL_MARKER).exists())


if __name__ == "__main__":
    unittest.main()
