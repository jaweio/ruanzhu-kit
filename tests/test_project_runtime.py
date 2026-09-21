import argparse
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import project_runtime


class ProjectRuntimeTests(unittest.TestCase):
    def test_detect_commands_finds_package_script_without_starting(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "package.json").write_text('{"scripts":{"dev":"vite"}}', encoding="utf-8")
            candidates = project_runtime.detect_commands(repo)
            self.assertEqual(candidates[0]["command"], "npm run dev")
            self.assertEqual(candidates[0]["role"], "frontend")

    def test_start_requires_explicit_allow_run(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(repo=directory, allow_run=False, command="python3 -c 'pass'",
                                      cwd=None, role="service", port=None)
            self.assertEqual(project_runtime.start(args), 2)


if __name__ == "__main__":
    unittest.main()
