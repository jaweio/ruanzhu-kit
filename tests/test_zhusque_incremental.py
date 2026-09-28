import contextlib
import hashlib
import io
import json
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import artifact_manifest
import zhusque_check as z
import zhusque_incremental as inc


def result(risk=0, channel="api"):
    return {"status": "success", "labels_ratio": {"0": 1 - risk, "1": risk, "2": 0},
            "segment_labels": [], "channel": channel,
            "makers_models_usage": {"total_tokens": 123}}


class SplitTests(unittest.TestCase):
    def test_trailing_whitespace_never_drops_last_paragraph(self):
        for text in ("前段\n\n末段\n", "甲\n", "甲 \n\n乙 \n\t", "标题\n\n" + "正文" * 400 + "\n"):
            self.assertEqual("".join(re.sub(r"\s", "", x["text"]) for x in inc.split_units(text, 2000)),
                             re.sub(r"\s", "", text))

    def test_all_nonwhitespace_covered_once_and_bounded(self):
        rng = random.Random(61)
        for limit in (3, 350, 700, 800, 2000):
            for _ in range(20):
                text = "\n\n".join("正文。" * rng.randrange(1, 1000) for _ in range(8)) + "\n"
                units = inc.split_units(text, limit)
                self.assertEqual("".join(re.sub(r"\s", "", u["text"]) for u in units), re.sub(r"\s", "", text))
                self.assertTrue(all(0 < len(u["text"]) <= limit for u in units))
                self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(units, units[1:])))

    def test_edit_does_not_shift_following_paragraph_blocks(self):
        paras = [chr(0x4e00 + i) * 800 for i in range(4)]
        original = inc.split_units("\n\n".join(paras), 2000)
        paras[1] += "修改"
        revised = inc.split_units("\n\n".join(paras), 2000)
        self.assertEqual([u["text"] for u in original][2:], [u["text"] for u in revised][2:])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.doc = self.root / "软件说明书.md"
        self.doc.write_text("甲" * 800 + "\n\n" + "乙" * 800 + "\n", encoding="utf-8")
        self.key = patch.object(z, "resolve_key", return_value=("test-only", "mock")).start()
        self.cache = patch.object(z, "cache_directory", return_value=self.root / "cache").start()
        self.api = patch.object(z, "request_model", return_value=result()).start()
        self.addCleanup(patch.stopall)

    def run_check(self, **overrides):
        args = dict(targets=[str(self.root)], channel="api", plan=False, max_risk_ratio=.2,
                    max_chars=2000, allow_upload=True, no_cache=False, finalize=True, report=None,
                    browser_timeout=1)
        args.update(overrides)
        with contextlib.redirect_stdout(io.StringIO()):
            return inc.run(SimpleNamespace(**args))

    def state(self):
        return json.loads((self.root / inc.STATE_NAME).read_text())

    def test_first_full_unchanged_zero_then_single_changed_unit(self):
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.api.call_count, 2)
        self.assertTrue(artifact_manifest._zhusque_status(self.root)["checked"])
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.api.call_count, 2)
        self.assertEqual(self.state()["stats"]["makers_tokens"], 0)
        self.doc.write_text(self.doc.read_text().replace("甲", "改", 1), encoding="utf-8")
        self.assertFalse(artifact_manifest._zhusque_status(self.root)["checked"])
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.api.call_count, 3)
        self.assertEqual(self.state()["stats"]["makers_tokens"], 123)

    def test_duplicate_content_only_uploaded_once(self):
        self.doc.write_text("甲" * 800 + "\n\n" + "甲" * 800)
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.api.call_count, 1)

    def test_cached_cua_result_keeps_provenance_in_report(self):
        self.doc.write_text("甲" * 800, encoding="utf-8")
        recorded = result(channel="web")
        recorded["evidence"] = {"source": "computer_use"}
        key = z.cache_key(z.WEB_URL, z.DEFAULT_MODEL, 2000, "甲" * 800)
        z.save_cached_result(self.root / "cache", key, recorded)
        self.assertEqual(self.run_check(channel="web"), 0)
        self.assertIn("web / computer use（缓存）", (self.root / "朱雀检测报告.md").read_text())
        self.api.assert_not_called()

    def test_short_paragraph_addition_preserves_later_cached_blocks(self):
        paras = [f"段落{i:03d}。" + chr(0x4e00 + i) * 115 for i in range(100)]
        self.doc.write_text("\n\n".join(paras) + "\n")
        self.assertEqual(self.run_check(), 0)
        first_calls = self.api.call_count
        self.assertGreater(first_calls, 10)
        paras[0] += "补充细节" * 30
        self.doc.write_text("\n\n".join(paras) + "\n")
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.api.call_count - first_calls, 1)
        self.assertEqual(self.state()["stats"]["cached_units"], first_calls - 1)
        # Inserting a new short paragraph affects nearby context, not the tail.
        paras.insert(0, "新增前言。" * 20)
        self.doc.write_text("\n\n".join(paras) + "\n")
        before = self.api.call_count
        self.assertEqual(self.run_check(), 0)
        self.assertLessEqual(self.api.call_count - before, 2)
        self.assertGreaterEqual(self.state()["stats"]["cached_units"], first_calls - 2)

    def test_resume_partial_failure_only_uploads_pending(self):
        self.api.side_effect = [result(), RuntimeError("failed")]
        self.assertEqual(self.run_check(), 2)
        self.assertFalse((self.root / z.FINAL_MARKER).exists())
        self.assertEqual(self.state()["stats"]["uploaded_units"], 1)
        self.api.side_effect = None
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.api.call_count, 3)

    def test_high_risk_has_current_review_status_but_never_passes(self):
        self.api.return_value = result(.7)
        self.assertEqual(self.run_check(), 1)
        status = artifact_manifest._zhusque_status(self.root)
        self.assertFalse(status["checked"])
        self.assertTrue(status["content_match"])
        self.assertTrue(status["coverage_complete"])
        self.assertAlmostEqual(status["risk_ratio"], .7)
        self.assertEqual(self.run_check(), 1)
        self.assertEqual(self.api.call_count, 2)

    def test_forced_check_failure_invalidates_previous_passing_marker(self):
        self.assertEqual(self.run_check(), 0)
        self.api.side_effect = RuntimeError("failed")
        self.assertEqual(self.run_check(no_cache=True, finalize=False), 2)
        self.assertFalse(artifact_manifest._zhusque_status(self.root)["checked"])

    def test_tightened_threshold_uses_cache_without_passing(self):
        self.api.return_value = result(.1)
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.run_check(max_risk_ratio=.05), 1)
        self.assertEqual(self.api.call_count, 2)
        self.assertFalse(artifact_manifest._zhusque_status(self.root)["checked"])

    def test_plan_does_not_resolve_key_or_call_transport(self):
        self.assertEqual(self.run_check(plan=True, allow_upload=False), 0)
        self.key.assert_not_called()
        self.api.assert_not_called()
        self.assertFalse((self.root / inc.STATE_NAME).exists())

    def test_source_mutation_during_request_cannot_pass(self):
        def mutate(*args):
            self.doc.write_text(self.doc.read_text() + "变更")
            return result()
        self.api.side_effect = mutate
        self.assertEqual(self.run_check(), 2)
        self.assertEqual(self.state()["stats"]["blocked"], "source_changed_during_detection")
        self.assertFalse(artifact_manifest._zhusque_status(self.root)["checked"])

    def test_no_key_auto_and_failed_api_both_fall_back_to_web(self):
        import zhusque_browser
        def web(text, request_id, **options):
            return {**result(channel="web"), "evidence": {"text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "page_record": "local-record.json", "ratio_source": "visible-segment-nonwhitespace-character-weighted"}}
        with patch.object(zhusque_browser, "BrowserDetector") as browser:
            browser.return_value.detect.side_effect = web
            self.key.return_value = (None, None)
            self.assertEqual(self.run_check(channel="auto"), 0)
            self.api.assert_not_called()
            self.assertEqual(browser.return_value.detect.call_count, 2)
            self.assertEqual(self.state()["stats"]["makers_tokens"], 0)
            self.key.return_value = ("test-only", "mock")
            self.api.side_effect = RuntimeError("failed")
            self.assertEqual(self.run_check(channel="auto", no_cache=True), 0)
            self.assertEqual(self.api.call_count, 1)
            self.assertEqual(browser.return_value.detect.call_count, 4)

    def test_web_wrong_text_hash_rejected(self):
        import zhusque_browser
        with patch.object(zhusque_browser, "BrowserDetector") as browser:
            browser.return_value.detect.return_value = {**result(channel="web"), "evidence": {"text_sha256": "wrong"}}
            self.assertEqual(self.run_check(channel="web"), 2)
            self.assertFalse((self.root / z.FINAL_MARKER).exists())

    def test_short_web_unit_does_not_block_remaining_long_text(self):
        import zhusque_browser
        self.doc.write_text("短文\n")
        other = self.root / "申请表填报文案.md"
        other.write_text("实际描述" * 200)
        with patch.object(zhusque_browser, "BrowserDetector") as browser:
            browser.return_value.detect.side_effect = lambda text, request_id: {
                **result(channel="web"), "delivery": "resumed", "evidence": {"text_sha256": request_id}}
            self.assertEqual(self.run_check(channel="web"), 2)
            self.assertEqual(browser.return_value.detect.call_count, 1)
            self.assertEqual(self.state()["stats"]["resumed_units"], 1)
            self.assertEqual(self.state()["stats"]["uploaded_units"], 0)
            self.assertFalse(artifact_manifest._zhusque_status(self.root)["checked"])

    def test_explicit_api_does_not_reuse_web_cache(self):
        row = inc.collect_units([self.doc], 2000)[0][0]
        z.save_cached_result(self.root / "cache", z.cache_key(z.WEB_URL, z.DEFAULT_MODEL, 2000, row["text"]), result(channel="web"))
        self.assertIsNone(inc.cached_unit(row, self.root / "cache", z.DEFAULT_BASE_URL, z.DEFAULT_MODEL, 2000, "api"))

    def test_weighting_and_position_length_not_end(self):
        rows = [{"chars": 100, "result": result(1)}, {"chars": 900, "result": result(0)}]
        self.assertAlmostEqual(inc.totals(rows)["risk_ratio"], .1)
        row = {"file": str(self.doc), "heading": "正文", "line": 1, "index": 1, "id": "x" * 64,
               "text": "甲乙丙丁戊己庚辛壬癸", "result": {**result(.2), "segment_labels": [{"label": 1, "position": [4, 2]}]}}
        path = self.root / "任务.md"
        inc.write_rewrite_tasks(path, [row])
        self.assertIn("> 戊己\n", path.read_text())
        self.assertNotIn("> 戊己庚", path.read_text())


if __name__ == "__main__":
    unittest.main()
