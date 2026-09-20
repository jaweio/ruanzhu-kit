#!/usr/bin/env python3
"""Explicit Git installation/update. Never overwrite an unmanaged or dirty copy."""
import argparse
import subprocess
from pathlib import Path

DEFAULT_SOURCE = 'https://github.com/jaweio/ruanzhu-kit.git'


def git(*args):
    return subprocess.run(['git', *map(str, args)], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def manage(action, dest, source=DEFAULT_SOURCE):
    dest = Path(dest).expanduser().absolute()
    if action == 'install':
        if dest.exists():
            raise ValueError(f'目录已存在，未覆盖：{dest}。请备份旧目录或选择其他目录。')
        dest.parent.mkdir(parents=True, exist_ok=True)
        git('clone', '--branch', 'main', '--', source, dest)
    else:
        if not (dest / '.git').is_dir():
            raise ValueError('目标不是 Git 安装，请备份旧目录后重新安装。')
        if git('-C', dest, 'rev-parse', '--show-toplevel') != str(dest.resolve()):
            raise ValueError('目标必须是此 skill 的仓库根目录。')
        if git('-C', dest, 'remote', 'get-url', 'origin') != source:
            raise ValueError('origin 与指定发布仓库不一致，已停止。')
        if git('-C', dest, 'status', '--porcelain'):
            raise ValueError('存在本地修改或未跟踪文件，已停止；请先备份并处理这些文件。')
        if git('-C', dest, 'branch', '--show-current') != 'main':
            raise ValueError('当前不在 main 分支，已停止。固定版本用户请主动切回 main 后更新。')
        git('-C', dest, 'pull', '--ff-only', 'origin', 'main')
    return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['install', 'update'])
    p.add_argument('--dest', required=True, help='安装目录')
    p.add_argument('--source', default=DEFAULT_SOURCE, help='Git 源（默认官方仓库）')
    a = p.parse_args()
    try:
        dest = manage(a.action, a.dest, a.source)
    except (ValueError, subprocess.CalledProcessError) as e:
        p.exit(1, f'{getattr(e, "stderr", None) or str(e)}\n')
    version = (dest / 'VERSION').read_text().strip() if (dest / 'VERSION').exists() else 'unknown'
    print(f'{a.action} 完成：{dest}，版本 {version}。请重新开启 agent 会话。')


if __name__ == '__main__':
    main()
