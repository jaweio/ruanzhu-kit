import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import zhusque_incremental as inc  # noqa: E402


class ManualFallbackTests(unittest.TestCase):
    def test_copies_text_and_opens_page_when_no_browser_window(self):
        with patch.object(inc, "copy_to_clipboard", return_value=True) as copy, \
                patch("webbrowser.open", return_value=True) as opener:
            state = inc.manual_fallback("待检测的说明书段落", open_page=True)
        copy.assert_called_once_with("待检测的说明书段落")
        opener.assert_called_once()
        self.assertIn("matrix.tencent.com", opener.call_args[0][0])
        self.assertEqual(state, {"copied": True, "opened": True, "chars": 9})

    def test_keeps_existing_window_without_opening_another(self):
        with patch.object(inc, "copy_to_clipboard", return_value=True), \
                patch("webbrowser.open") as opener:
            state = inc.manual_fallback("段落", open_page=False)
        opener.assert_not_called()
        self.assertFalse(state["opened"])

    def test_clipboard_failure_is_reported_not_raised(self):
        with patch("shutil.which", return_value=None):
            self.assertFalse(inc.copy_to_clipboard("x"))


if __name__ == "__main__":
    unittest.main()
