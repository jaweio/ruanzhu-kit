import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_update import check, LIMIT


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest = Path(self.temp.name)
        (self.dest / 'VERSION').write_text('1.0.0')

    def opener(self, data):
        return Mock(return_value=io.BytesIO(json.dumps(data).encode()))

    def test_new_release_and_no_writes(self):
        before = (self.dest / 'VERSION').read_bytes()
        open_url = self.opener({'tag_name': 'v1.0.1'})
        result = check(self.dest, opener=open_url)
        self.assertEqual(result['status'], 'update_available')
        self.assertEqual(result['release_url'], 'https://github.com/jaweio/ruanzhu-kit/releases/tag/v1.0.1')
        self.assertEqual((self.dest / 'VERSION').read_bytes(), before)
        self.assertEqual(list(self.dest.iterdir()), [self.dest / 'VERSION'])
        self.assertEqual(open_url.call_args.kwargs['timeout'], 4)

    def test_same_version(self):
        self.assertEqual(check(self.dest, opener=self.opener({'tag_name':'v1.0.0'}))['status'], 'current')

    def test_semantic_comparison(self):
        (self.dest / 'VERSION').write_text('1.9.0')
        self.assertEqual(check(self.dest, opener=self.opener({'tag_name':'v1.10.0'}))['status'], 'update_available')

    def test_local_newer_never_requests_downgrade(self):
        self.assertEqual(check(self.dest, opener=self.opener({'tag_name':'v0.9.0'}))['status'], 'local_newer')

    def test_network_timeout_is_nonblocking(self):
        result = check(self.dest, opener=Mock(side_effect=TimeoutError('private proxy address')))
        self.assertEqual(result['status'], 'check_failed')
        self.assertNotIn('private proxy', json.dumps(result))

    def test_rate_limit_is_nonblocking(self):
        error = HTTPError('https://api.github.com', 429, 'rate limit', {}, None)
        self.assertEqual(check(self.dest, opener=Mock(side_effect=error))['status'], 'check_failed')

    def test_invalid_metadata(self):
        for data in [[], {}, {'tag_name': '../../bad'}, {'tag_name': None}, {'tag_name': 'v2.0.0', 'prerelease': True}]:
            with self.subTest(data=data):
                self.assertEqual(check(self.dest, opener=self.opener(data))['status'], 'check_failed')

    def test_response_size_is_bounded(self):
        self.assertEqual(check(self.dest, opener=Mock(return_value=io.BytesIO(b'x'*(LIMIT+1))))['status'], 'check_failed')

    def test_missing_version_does_not_contact_network(self):
        (self.dest / 'VERSION').unlink()
        open_url = Mock()
        self.assertEqual(check(self.dest, opener=open_url)['status'], 'check_failed')
        open_url.assert_not_called()

    def test_cli_failure_is_zero_exit(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/check_update.py'),
                                 '--dest', str(self.dest / 'missing'), '--json'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['status'], 'check_failed')


if __name__ == '__main__':
    unittest.main()
