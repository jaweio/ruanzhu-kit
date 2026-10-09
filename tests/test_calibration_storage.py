import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import aigc_calibrate  # noqa: E402
import package_release  # noqa: E402


class CalibrationStorageTests(unittest.TestCase):
    def test_empty_private_library_does_not_claim_accuracy(self):
        with tempfile.TemporaryDirectory() as td:
            library = Path(td) / "private"
            self.assertEqual(aigc_calibrate.load_labels(library), [])
            with self.assertRaises(SystemExit) as caught:
                aigc_calibrate.evaluate([], verbose=False, library=library)
            self.assertIn("未进行准确率评估", str(caught.exception))

    def test_added_sample_stays_in_selected_library(self):
        with tempfile.TemporaryDirectory() as td:
            library = Path(td) / "private"
            labels = []
            name = aigc_calibrate.add_sample(labels, "提交文件后返回摘要。", 0.2,
                                             "已脱敏", "manual.txt", library)
            aigc_calibrate.save_labels(labels, library)
            self.assertEqual(name, "samples/s001.md")
            self.assertTrue((library / name).is_file())
            self.assertEqual(aigc_calibrate.load_labels(library)[0]["file"], name)

    def test_release_package_excludes_calibration_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in package_release.TOP_FILES:
                path = root / name
                path.write_text("name: ruanzhu-kit\n" if name == "SKILL.md"
                                else "1.0.11\n" if name == "VERSION" else "", encoding="utf-8")
            private = root / "assets" / "aigc-calibration" / "samples"
            private.mkdir(parents=True)
            (private / "s001.md").write_text("private sample", encoding="utf-8")
            (root / "assets" / "keep.json").write_text("{}", encoding="utf-8")
            archive = package_release.build(root)
            with zipfile.ZipFile(archive) as zipped:
                names = zipped.namelist()
            self.assertTrue(any(name.endswith("assets/keep.json") for name in names))
            self.assertFalse(any("aigc-calibration" in name for name in names))


if __name__ == "__main__":
    unittest.main()
