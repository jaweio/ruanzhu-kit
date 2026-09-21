#!/usr/bin/env python3
"""软著流程的可选本地运行会话管理器。

材料分析和生成不依赖它。该脚本只负责探测候选启动命令，或在明确
传入 --allow-run 后把开发进程放入可停止的本地会话并记录日志。
"""

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


SKIP_DIRS = {"node_modules", ".git", "dist", "build", "target", ".next", ".nuxt", "vendor", "__pycache__"}
SESSION_DIR = ".ruanzhu/runtime"


def rel_parts(path, repo):
    return set(path.relative_to(repo).parts)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def classify(path, command, package):
    text = f"{path} {command} {package}".lower()
    if any(x in text for x in ("frontend", "front-end", "vite", "next", "nuxt", "webpack", "astro", "react", "vue")):
        return "frontend"
    if any(x in text for x in ("backend", "back-end", "server", "api", "spring", "django", "fastapi", "flask", "nest")):
        return "backend"
    return "service"


def detect_commands(repo):
    candidates = []
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
            continue
        if any(part in SKIP_DIRS for part in rel_parts(path, repo)):
            continue
        rel = str(path.relative_to(repo))
        if path.name == "package.json":
            package = read_json(path)
            scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            if not isinstance(scripts, dict):
                continue
            command = next((f"npm run {name}" for name in ("dev", "start", "serve", "preview") if name in scripts), None)
            if command:
                candidates.append({"role": classify(rel, command, package), "cwd": str(path.parent),
                                   "command": command, "source": rel})
        elif path.name == "pom.xml":
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "spring-boot" in text or "springframework" in text:
                candidates.append({"role": "backend", "cwd": str(path.parent),
                                   "command": "mvn spring-boot:run", "source": rel})
        elif path.name == "manage.py":
            candidates.append({"role": "backend", "cwd": str(path.parent),
                               "command": "python3 manage.py runserver 127.0.0.1:8000", "source": rel})
        elif path.name == "go.mod" and (path.parent / "main.go").exists():
            candidates.append({"role": "backend", "cwd": str(path.parent), "command": "go run .", "source": rel})
        elif path.name == "Cargo.toml" and (path.parent / "src" / "main.rs").exists():
            candidates.append({"role": "service", "cwd": str(path.parent), "command": "cargo run", "source": rel})
    # 同一目录下多个 package.json 只保留第一个候选，避免误启动 workspace 子包。
    seen = set()
    unique = []
    for item in candidates:
        key = (item["cwd"], item["command"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def session_path(repo):
    return repo / SESSION_DIR / "session.json"


def load_session(repo):
    path = session_path(repo)
    return read_json(path) if path.exists() else {}


def print_candidates(candidates, as_json=False):
    if as_json:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return
    if not candidates:
        print("没有识别到可用的本地启动命令。可在 start 时显式传 --command。")
        return
    print("角色       工作目录                          启动命令")
    print("-" * 78)
    for item in candidates:
        print(f"{item['role']:<10} {item['cwd']:<34} {item['command']}")


def safe_command(command):
    if any(token in command for token in ("&&", "||", ";", "|", ">", "<", "`", "$()")):
        raise ValueError("启动命令不能包含 shell 串联、重定向或命令替换；请拆成单条命令。")
    parts = shlex.split(command)
    if not parts:
        raise ValueError("启动命令为空。")
    return parts


def choose_candidate(candidates, role):
    preferred = [item for item in candidates if item["role"] == role]
    return preferred[0] if preferred else (candidates[0] if candidates else None)


def start(args):
    if not args.allow_run:
        print("启动项目会创建本地进程。确认后请加 --allow-run。", file=sys.stderr)
        return 2
    repo = Path(args.repo).resolve()
    candidates = detect_commands(repo)
    session_dir = repo / SESSION_DIR
    session_dir.mkdir(parents=True, exist_ok=True)
    old = load_session(repo)
    if old and any(p.get("running") for p in old.get("processes", [])):
        print(f"已有运行会话：{session_path(repo)}；先执行 stop 或使用其他 Worktree。", file=sys.stderr)
        return 2
    selected = []
    if args.command:
        selected.append({"role": args.role, "cwd": str(Path(args.cwd or repo).resolve()), "command": args.command, "source": "显式命令"})
    else:
        for role in ("frontend", "backend"):
            candidate = choose_candidate(candidates, role)
            if candidate:
                selected.append(candidate)
        if not selected and candidates:
            selected.append(candidates[0])
    if not selected:
        print("没有可启动命令；请传 --command 和 --cwd。", file=sys.stderr)
        return 2

    session = {"session_id": uuid.uuid4().hex, "repo": str(repo), "started_at": time.time(), "processes": []}
    started = []
    try:
        for item in selected:
            command = item["command"]
            parts = safe_command(command)
            cwd = Path(item["cwd"])
            if not cwd.is_dir():
                raise RuntimeError(f"工作目录不存在：{cwd}")
            log_path = session_dir / f"{item['role']}-{len(session['processes']) + 1}.log"
            log = log_path.open("ab")
            env = os.environ.copy()
            env.update({"RUANZHU_RUNTIME": "1", "NODE_ENV": env.get("NODE_ENV", "development"), "HOST": "127.0.0.1"})
            if args.port and len(selected) == 1:
                env["PORT"] = str(args.port)
            try:
                proc = subprocess.Popen(parts, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=True)
            finally:
                log.close()
            started.append(proc)
            session["processes"].append({"role": item["role"], "pid": proc.pid, "cwd": str(cwd),
                                         "command": command, "log": str(log_path), "running": True})
            print(f"已启动 {item['role']} PID={proc.pid}，日志：{log_path}")
    except Exception:
        for proc in started:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
        raise
    session_path(repo).write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"运行会话：{session_path(repo)}")
    return 0


def status(args):
    repo = Path(args.repo).resolve()
    session = load_session(repo)
    if not session:
        print("没有运行会话。")
        return 0
    rows = []
    for item in session.get("processes", []):
        running = False
        try:
            os.kill(int(item["pid"]), 0)
            running = True
        except (OSError, ValueError, KeyError):
            running = False
        item["running"] = running
        rows.append({"role": item.get("role"), "pid": item.get("pid"), "running": running, "log": item.get("log")})
    session_path(repo).write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"session_id": session.get("session_id"), "processes": rows}, ensure_ascii=False, indent=2))
    return 0


def stop(args):
    repo = Path(args.repo).resolve()
    session = load_session(repo)
    if not session:
        print("没有运行会话。")
        return 0
    for item in session.get("processes", []):
        try:
            os.killpg(int(item["pid"]), signal.SIGTERM)
            print(f"已停止 {item.get('role')} PID={item.get('pid')}")
        except (OSError, ValueError, KeyError):
            pass
        item["running"] = False
    session["stopped_at"] = time.time()
    session_path(repo).write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def health(args):
    for url in args.url:
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as response:
                print(f"✓ {url} HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"× {url} {exc}")
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="ruanzhu-kit 可选本地项目运行会话管理器")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="只分析启动命令，不启动项目")
    inspect.add_argument("--repo", required=True)
    inspect.add_argument("--json", action="store_true")
    start_parser = sub.add_parser("start", help="显式启动本地开发会话")
    start_parser.add_argument("--repo", required=True)
    start_parser.add_argument("--allow-run", action="store_true")
    start_parser.add_argument("--command", help="单条启动命令；不传则从项目配置推断")
    start_parser.add_argument("--cwd")
    start_parser.add_argument("--role", default="service", choices=["frontend", "backend", "service"])
    start_parser.add_argument("--port", type=int)
    start_parser.set_defaults(handler=start)
    for name, fn in (("status", status), ("stop", stop)):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.set_defaults(handler=fn)
    health_parser = sub.add_parser("health", help="检查指定本地服务")
    health_parser.add_argument("url", nargs="+", help="如 http://127.0.0.1:5173")
    health_parser.add_argument("--timeout", type=float, default=3)
    health_parser.set_defaults(handler=health)
    args = parser.parse_args()
    if args.command == "inspect":
        print_candidates(detect_commands(Path(args.repo).resolve()), args.json)
        return 0
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
