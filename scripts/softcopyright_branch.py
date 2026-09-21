#!/usr/bin/env python3
"""管理软著专用 Git 分支/工作树，并检查多份软著的源码重叠。

脚本不会自动 push，也不会修改主分支。创建分支必须显式提供 ``--apply``，
默认把工作树放在仓库外的 ``.ruanzhu-worktrees`` 目录，便于在独立目录中
做软著代码级脱敏、重命名和模块组合。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def slugify(value):
    text = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", str(value).strip()).strip("-._")
    return text.lower() or "copyright"


def branch_name(value):
    raw = str(value).strip()
    if raw.startswith("copyright/"):
        return "copyright/" + slugify(raw.split("/", 1)[1])
    return f"copyright/{slugify(raw)}"


def run_git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} 失败")
    return result


def list_worktrees(repo):
    result = run_git(repo, "worktree", "list", "--porcelain")
    blocks = []
    current = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        blocks.append(current)
    return blocks


def read_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取配置：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError("配置顶层必须是对象")
    projects = data.get("projects")
    if not isinstance(projects, list):
        raise ValueError("配置缺少 projects 数组")
    data["_config_dir"] = str(Path(path).expanduser().resolve().parent)
    return data


def normalize_file(value):
    return str(value).replace("\\", "/").lstrip("./")


def overlap_report(config, repo=None):
    owners = {}
    missing = []
    root_value = repo or config.get("repo_root") or config.get("_config_dir") or "."
    root = Path(root_value).expanduser().resolve()
    for project in config.get("projects", []):
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("id") or project.get("name") or "未命名项目")
        for file_name in project.get("source_files", []) or []:
            rel = normalize_file(file_name)
            owners.setdefault(rel, []).append(project_id)
            if not (root / rel).is_file():
                missing.append({"project": project_id, "file": rel})
    overlaps = {name: values for name, values in owners.items() if len(set(values)) > 1}
    return {"overlaps": overlaps, "missing": missing, "file_count": len(owners)}


def create_worktree(repo, name, base, worktree, apply=False):
    repo = Path(repo).expanduser().resolve()
    if not (repo / ".git").exists() and run_git(repo, "rev-parse", "--show-toplevel", check=False).returncode:
        raise ValueError(f"不是 Git 仓库：{repo}")
    branch = branch_name(name)
    target = Path(worktree).expanduser().resolve() if worktree else repo.parent / ".ruanzhu-worktrees" / slugify(name)
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"工作树目录非空，为避免覆盖已停止：{target}")
    if not apply:
        print(f"[预览] git worktree add -b {branch} {target} {base}")
        return {"branch": branch, "worktree": str(target), "applied": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(repo, "worktree", "add", "-b", branch, str(target), base)
    print(result.stdout.strip() or f"已创建工作树：{target}")
    return {"branch": branch, "worktree": str(target), "applied": True}


def main():
    parser = argparse.ArgumentParser(description="软著分支/工作树和源码重叠检查")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="创建软著专用分支和独立工作树")
    create.add_argument("--repo", required=True, help="Git 仓库目录")
    create.add_argument("--name", required=True, help="软著标识，例如 ai-collab-backend")
    create.add_argument("--base", default="HEAD", help="基线分支或提交（默认 HEAD）")
    create.add_argument("--worktree", help="工作树目录；默认放在仓库外 .ruanzhu-worktrees")
    create.add_argument("--apply", action="store_true", help="真正创建，不提供则仅预览")
    status = sub.add_parser("status", help="查看现有工作树")
    status.add_argument("--repo", required=True)
    check = sub.add_parser("check-overlap", help="检查 projects.source_files 是否重叠或缺失")
    check.add_argument("--config", required=True)
    check.add_argument("--repo", help="源码仓库根目录；未提供时使用配置 repo_root 或配置文件目录")
    check.add_argument("--fail-on-overlap", action="store_true", help="发现重叠时返回失败")
    args = parser.parse_args()
    try:
        if args.command == "create":
            create_worktree(args.repo, args.name, args.base, args.worktree, args.apply)
        elif args.command == "status":
            print(json.dumps(list_worktrees(Path(args.repo).expanduser().resolve()), ensure_ascii=False, indent=2))
        else:
            report = overlap_report(read_config(args.config), args.repo)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.fail_on_overlap and report["overlaps"]:
                return 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
