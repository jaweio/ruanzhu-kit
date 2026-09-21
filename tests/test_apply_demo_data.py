import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import apply_demo_data


class ApplyDemoDataTests(unittest.TestCase):
    def test_render_keeps_types_and_replaces_nested_values(self):
        value = apply_demo_data.render(
            {"title": "{{ name }}", "count": "{{record_no}}", "items": ["{{project}}-{{name}}"]},
            {"name": "订单一", "record_no": 2, "project": "协作系统"},
        )
        self.assertEqual(value["title"], "订单一")
        self.assertEqual(value["count"], 2)
        self.assertEqual(value["items"], ["协作系统-订单一"])

    def test_nonlocal_write_is_blocked_by_default(self):
        self.assertTrue(apply_demo_data.host_allowed("http://127.0.0.1:8000"))
        self.assertFalse(apply_demo_data.host_allowed("https://example.com"))
        self.assertTrue(apply_demo_data.host_allowed("https://example.com", allow_nonlocal=True))

    def test_dry_run_does_not_create_rollback_file(self):
        plan = {"project": "协作系统", "records": [{"record_no": 1, "values": {"name": "订单一"}}]}
        config = {"base_url": "http://127.0.0.1:8000", "requests": [{
            "name": "创建订单", "method": "POST", "path": "/api/orders",
            "payload": {"name": "{{name}}"}, "rollback": {"method": "DELETE", "path": "/api/orders/{{id}}"},
        }]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollback.json"
            actions = apply_demo_data.apply_plan(plan, config, allow_write=False, rollback_file=path)
            self.assertEqual(actions[0]["status"], "preview")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
