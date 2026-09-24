#!/usr/bin/env python3
"""提交前本地工作流冒烟检查。

覆盖不需要登录、验证码或运行项目的关键链路：正式材料清单、文件存在性、截图清单、
AIGC 目录范围和版权产出闸门。真实浏览器填表、项目启动和外部 API 仍需人工/独立 E2E。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_manifest import build_manifest  # noqa: E402
from aigc_check import analyze, collect  # noqa: E402
from copyright_check import Findings, check_materials  # noqa: E402
from screenshots import validate_manifest  # noqa: E402


def run(config_path, repo=None):
    config_path = Path(config_path).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    if not root.is_absolute():
        candidates = [config_path.parent / root, config_path.parent, Path.cwd() / root]
        root = next((candidate for candidate in candidates
                     if any((candidate / p.get("id", "")).exists() for p in cfg.get("projects", []))), candidates[0])
    result = {"config": str(config_path), "projects": [], "copyright": {"high": 0, "medium": 0, "low": 0}}
    for project in cfg.get("projects", []):
        d = root / project["id"]
        manifest = build_manifest(config_path, cfg, project, root)
        formal_ok = not manifest["checks"]
        targets = collect([d]) if d.exists() else []
        scores = [{"file": str(p), "score": analyze(p)["score"]} for p in targets]
        shots = validate_manifest(d, cfg.get("manual_spec")) if d.exists() else {"exists": False, "ok": False}
        result["projects"].append({
            "id": project["id"],
            "formal_manifest": formal_ok,
            "manifest_checks": manifest["checks"],
            "aigc_targets": scores,
            "screenshots": shots,
        })
    findings = Findings()
    check_materials(root, cfg, findings)
    for item in findings.items:
        result["copyright"][item["severity"]] += 1
    result["ok"] = bool(result["projects"]) and all(
        p["formal_manifest"] and result["copyright"]["high"] == 0 for p in result["projects"]
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="ruanzhu-kit 提交前本地工作流冒烟检查")
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo", help="保留参数，冒烟检查不启动项目")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="正式清单或版权高危存在时返回 1")
    args = parser.parse_args()
    result = run(args.config, args.repo)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for project in result["projects"]:
            print(f"{project['id']}: 清单 {'OK' if project['formal_manifest'] else '缺失/不一致'}，"
                  f"AIGC 目标 {len(project['aigc_targets'])}，截图 {'OK' if project['screenshots'].get('ok') else '待补'}")
        print("版权：" + " / ".join(f"{k} {v}" for k, v in result["copyright"].items()))
        print("冒烟检查通过" if result["ok"] else "冒烟检查未通过")
    return 0 if result["ok"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
