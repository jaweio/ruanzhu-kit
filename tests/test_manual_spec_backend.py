import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ManualSpecBackendTests(unittest.TestCase):
    def test_extracts_api_facts_and_evidence_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = repo / "server" / "controller" / "items.go"
            source.parent.mkdir(parents=True)
            source.write_text('router.GET("/items", listItems)\nrouter.POST("/items", createItem)\n', encoding="utf-8")
            out = repo / "说明书素材.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "manual_spec.py"
            subprocess.run([sys.executable, str(script), "--repo", str(repo), "--out", str(out)], check=True)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(data["backend"])
            self.assertIn({"method": "GET", "path": "/items", "file": "server/controller/items.go", "line": 1}, data["apis"])
            self.assertEqual([x["id"] for x in data["evidence_plan"]],
                             ["api-docs", "api-success", "api-error", "runtime-log"])


if __name__ == "__main__":
    unittest.main()
