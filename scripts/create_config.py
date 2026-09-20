#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Create a reusable ruanzhu.config.json template.")
    parser.add_argument("--output", default="soft-copyright-materials/ruanzhu.config.json")
    parser.add_argument("--project-name", default="示例项目")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    template = skill_dir / "assets" / "ruanzhu.config.example.json"
    data = json.loads(template.read_text(encoding="utf-8"))
    data["project_name"] = args.project_name

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()

