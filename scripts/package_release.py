#!/usr/bin/env python3
"""Build deterministic skill archives from an explicit public-file allowlist."""
import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = ['SKILL.md', 'README.md', 'LICENSE', 'VERSION', 'CHANGELOG.md',
             'CONTRIBUTING.md', 'requirements.txt', '.gitignore']


def build(root=ROOT):
    version = (root / 'VERSION').read_text().strip()
    name = re.search(r'^name: ([a-z0-9-]+)$', (root / 'SKILL.md').read_text(), re.M).group(1)
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('VERSION must be X.Y.Z')
    entries = [root / n for n in TOP_FILES]
    for folder in ['scripts', 'references', 'assets', 'tests']:
        entries.extend(p for p in (root / folder).rglob('*') if p.is_file()
                       and '__pycache__' not in p.parts and 'node_modules' not in p.parts
                       and p.suffix in {'.py', '.js', '.json', '.md'}
                       and p.name != 'config.json')
    out = root / 'dist'
    out.mkdir(exist_ok=True)
    archive = out / f'{name}-{version}.skill'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(entries)):
            if p.is_symlink():
                raise ValueError(f'拒绝打包符号链接：{p}')
            info = zipfile.ZipInfo(f'{name}/{p.relative_to(root).as_posix()}', (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    stable = out / f'{name}.skill'
    stable.write_bytes(archive.read_bytes())
    sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in [archive, stable])
    (out / 'SHA256SUMS').write_text(sums)
    print(sums, end='')
    return archive


if __name__ == '__main__':
    build()
