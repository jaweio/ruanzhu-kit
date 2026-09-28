import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import artifact_manifest  # noqa: E402
import zhusque_check  # noqa: E402
import zhusque_incremental  # noqa: E402


class ZhusqueThresholdPinnedTests(unittest.TestCase):
    def marker_dir(self, td, risk, recorded_threshold):
        d = Path(td)
        (d / "软件说明书.md").write_text("# 软件概述\n进入首页。", encoding="utf-8")
        (d / "朱雀检测报告.md").write_text("报告", encoding="utf-8")
        (d / ".zhusque-final.json").write_text(json.dumps({
            "version": "zhuque-incremental-v3", "manifest": "m", "report": str(d / "朱雀检测报告.md"),
            "risk_ratio": risk, "max_risk_ratio": recorded_threshold, "coverage_complete": True,
        }), encoding="utf-8")
        return d

    def status(self, d):
        with patch.object(zhusque_check, "final_manifest", return_value="m"):
            return artifact_manifest._zhusque_status(d)

    def test_loosened_threshold_in_marker_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            state = self.status(self.marker_dir(td, risk=0.9, recorded_threshold=1.0))
            self.assertFalse(state["checked"])
            self.assertEqual(state["max_risk_ratio"], zhusque_check.DEFAULT_MAX_RISK_RATIO)

    def test_result_within_fixed_threshold_passes(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(self.status(self.marker_dir(td, risk=0.1, recorded_threshold=0.2))["checked"])

    def test_cli_refuses_to_loosen_threshold(self):
        args = SimpleNamespace(max_risk_ratio=0.5, max_chars=2000, channel="api", plan=True,
                               allow_upload=False, targets=["x"], finalize=True)
        with self.assertRaises(ValueError):
            zhusque_incremental.run(args)


if __name__ == "__main__":
    unittest.main()
