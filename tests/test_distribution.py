import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from manage_install import manage


def run(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = self.root / 'origin'
        self.origin.mkdir()
        run(self.origin, 'init', '-b', 'main')
        run(self.origin, 'config', 'user.name', 'Test')
        run(self.origin, 'config', 'user.email', 'test@example.com')
        self.commit('1.0.0')
        self.dest = self.root / 'installed'
        manage('install', self.dest, str(self.origin))

    def commit(self, version):
        (self.origin / 'VERSION').write_text(version)
        run(self.origin, 'add', 'VERSION')
        run(self.origin, 'commit', '-m', version)

    def test_update_fast_forward(self):
        self.commit('1.0.1')
        manage('update', self.dest, str(self.origin))
        self.assertEqual((self.dest / 'VERSION').read_text(), '1.0.1')

    def test_dirty_update_preserves_local_changes(self):
        (self.dest / 'VERSION').write_text('my edits')
        self.commit('1.0.1')
        with self.assertRaises(ValueError):
            manage('update', self.dest, str(self.origin))
        self.assertEqual((self.dest / 'VERSION').read_text(), 'my edits')

    def test_existing_install_is_not_overwritten(self):
        with self.assertRaises(ValueError):
            manage('install', self.dest, str(self.origin))

    def test_wrong_remote_is_refused(self):
        with self.assertRaises(ValueError):
            manage('update', self.dest, 'https://example.com/unexpected.git')

    def test_divergent_history_is_not_reset(self):
        run(self.dest, 'config', 'user.name', 'Test')
        run(self.dest, 'config', 'user.email', 'test@example.com')
        (self.dest / 'local.txt').write_text('local commit')
        run(self.dest, 'add', 'local.txt')
        run(self.dest, 'commit', '-m', 'local')
        before = run(self.dest, 'rev-parse', 'HEAD')
        self.commit('1.0.1')
        with self.assertRaises(subprocess.CalledProcessError):
            manage('update', self.dest, str(self.origin))
        self.assertEqual(run(self.dest, 'rev-parse', 'HEAD'), before)


if __name__ == '__main__':
    unittest.main()
