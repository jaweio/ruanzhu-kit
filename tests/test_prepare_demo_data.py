import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_demo_data


class PrepareDemoDataTests(unittest.TestCase):
    def test_plan_uses_project_semantics_and_skips_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "src").mkdir()
            (repo / "src" / "OrderForm.ts").write_text(
                'const payload = { "订单名称": "", "orderCode": "", "description": "", "password": "" };\n',
                encoding="utf-8",
            )
            plan = prepare_demo_data.build_plan(
                repo, "协作系统", {"pages": [{"module": "订单管理", "entry": "/orders", "elements": ["订单名称"]}]}, 2
            )
            values = [v for row in plan["records"] for v in row["values"].values()]
            self.assertTrue(values)
            self.assertTrue(all(prepare_demo_data.safe_value(v) for v in values))
            self.assertIn("password", plan["safety"]["sensitive_fields_skipped"])
            self.assertEqual(plan["screen_scenarios"][0]["entry"], "/orders")

    def test_generated_values_do_not_use_placeholder_words(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "page.vue").write_text('const title = "名称"; const status = "状态";', encoding="utf-8")
            plan = prepare_demo_data.build_plan(repo, "应用平台", {"pages": []}, 3)
            text = str(plan["records"])
            self.assertIsNone(prepare_demo_data.FORBIDDEN.search(text))


if __name__ == "__main__":
    unittest.main()
