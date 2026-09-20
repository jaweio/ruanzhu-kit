#!/usr/bin/env python3
"""Check the latest public release; never change installed files or block a task."""
import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = 'https://api.github.com/repos/jaweio/ruanzhu-kit/releases/latest'
RELEASES = 'https://github.com/jaweio/ruanzhu-kit/releases'
LIMIT = 65536


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value.strip())
    if not match:
        raise ValueError('版本格式应为 X.Y.Z')
    return tuple(map(int, match.groups()))


def check(dest=ROOT, timeout=4, opener=None):
    """One anonymous, bounded metadata request per invocation; no local writes."""
    result = {'status': 'check_failed', 'local_version': None,
              'latest_version': None, 'release_url': RELEASES}
    try:
        local = (Path(dest).expanduser() / 'VERSION').read_text().strip()
        local_numbers = version_tuple(local)
        result['local_version'] = local
        request = urllib.request.Request(LATEST, headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'ruanzhu-kit-update-check'})
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('版本响应超出大小限制')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('版本响应格式无效')
        if data.get('draft') or data.get('prerelease'):
            raise ValueError('暂未取得正式发布版本')
        tag = data.get('tag_name', '')
        if not isinstance(tag, str):
            raise ValueError('版本标签格式无效')
        latest_numbers = version_tuple(tag)
        result['latest_version'] = tag.removeprefix('v')
        result['release_url'] = RELEASES + '/tag/' + tag
        result['status'] = ('update_available' if latest_numbers > local_numbers else
                            'current' if latest_numbers == local_numbers else 'local_newer')
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        # Do not print raw network errors: proxies can embed private URLs in them.
        result['message'] = '暂时无法检查更新，继续使用本地版本。'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', type=Path, default=ROOT)
    parser.add_argument('--timeout', type=float, default=4)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not 0 < args.timeout <= 30:
        parser.error('--timeout 必须大于 0 且不超过 30 秒')
    result = check(args.dest, args.timeout)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif result['status'] == 'update_available':
        print(f"发现新版 {result['latest_version']}（本地 {result['local_version']}）。")
        print(result['release_url'])
        print('尚未修改本地文件；Git 安装可运行 manage_install.py update，压缩包安装可下载新包。')
    elif result['status'] == 'check_failed':
        print(result['message'])
    else:
        print(f"本地 {result['local_version']}，最新发布 {result['latest_version']}，无需更新。")
    # Failure to check must never prevent the user's actual task.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
