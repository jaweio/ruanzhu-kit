import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import form_plan  # noqa: E402


class FormPlanAccountFieldsTests(unittest.TestCase):
    def test_readonly_holder_is_account_sourced(self):
        fmap = json.loads((Path(__file__).resolve().parents[1] / "assets" / "r11-field-map.json").read_text())
        holder = next(f for step in fmap["steps"] for f in step["fields"] if f["key"].endswith("copyrightHolder"))
        self.assertEqual(holder["type"], "readonly")
        self.assertTrue(holder["verify"])

    def test_verify_accepts_logged_in_holder_without_local_baseline(self):
        fmap = {"steps": [{"fields": [{
            "key": "step2_basic.copyrightHolder", "label": "著作权人",
            "type": "readonly", "verify": True,
        }]}]}
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(json.dumps({"step2_basic": {"copyrightHolder": ""}}), encoding="utf-8")
            actual = {"copyrightHolder": "益搭科技有限公司"}
            self.assertEqual(form_plan.verify(json.loads(cfg.read_text()), fmap, actual), 0)
