import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preflight  # noqa: E402


class PreflightTests(unittest.TestCase):
    def test_required_result_shape(self):
        result = preflight.check()
        self.assertIn("ok", result)
        self.assertTrue(result["checks"])
        self.assertTrue({"name", "ok", "required", "detail", "fix"}.issubset(result["checks"][0]))

    def test_missing_required_dependency_fails_strict_result(self):
        with patch.object(preflight, "_which", return_value=None), \
             patch.object(preflight, "_font", return_value=None), \
             patch.object(preflight, "_module", side_effect=lambda name: name == "docx"):
            result = preflight.check()
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["required"] and not item["ok"] for item in result["checks"]))


if __name__ == "__main__":
    unittest.main()
