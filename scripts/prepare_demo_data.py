#!/usr/bin/env python3
"""为软著截图和说明书准备项目相关的合成演示数据。

默认只生成“数据方案”，不连接数据库、不调用远程接口，也不覆盖项目文件。
真正写入时应优先通过项目自己的本地 API 或浏览器/Computer Use 操作页面，
以便走完整的校验、权限和日志流程。
"""

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path


SKIP_DIR = re.compile(
    r"(?:^|/)(?:node_modules|vendor|dist|build|out|target|\.git|\.idea|\.vscode|coverage|"
    r"__pycache__|examples?|samples?|demo|mock|tests?|__tests__|源程序提取|说明书章节)(?:/|$)", re.I
)
TEXT_EXT = {
    ".vue", ".tsx", ".jsx", ".ts", ".js", ".wxml", ".axml", ".html", ".htm", ".dart",
    ".swift", ".kt", ".java", ".cs", ".xml", ".py", ".php", ".go", ".rs", ".sql",
    ".json", ".yaml", ".yml",
}
SENSITIVE = re.compile(
    r"(?:password|passwd|pwd|token|secret|private.?key|access.?key|api.?key|手机号|手机|身份证|"
    r"银行卡|银行账号|邮箱|email|authorization|cookie)", re.I
)
GENERIC = {
    "id", "uuid", "key", "value", "label", "title", "name", "type", "status", "data", "list",
    "item", "items", "index", "page", "size", "query", "params", "result", "message",
}
FORBIDDEN = re.compile(r"(?:测试|test|demo|mock|示例|sample|foo|bar|dummy)", re.I)

FIELD_PATTERNS = [
    re.compile(r"[\"'`]([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\-\u4e00-\u9fff]{1,32})[\"'`]\s*[:：]"),
    re.compile(r"^\s*(?:private|public|protected|static|final|readonly|lateinit\s+)*\s*[\w<>[\], ?|]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:[;=]|\()"),
    re.compile(r"(?:@JsonProperty|@Column|@Field)\s*\(\s*(?:value|name)?\s*=\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b\s+(?:varchar|char|text|int|integer|bigint|decimal|date|datetime|timestamp|boolean)\b", re.I),
]


def scan_files(repo):
    files = []
    for path in repo.rglob("*"):
        rel = "/" + str(path.relative_to(repo)).replace("\\", "/") + "/"
        if path.is_file() and not SKIP_DIR.search(rel) and path.suffix.lower() in TEXT_EXT:
            try:
                if path.stat().st_size <= 800_000:
                    files.append(path)
            except OSError:
                continue
    return files


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def clean_field(value):
    value = re.sub(r"\s+", "", str(value)).strip("_'`\" ")
    if (len(value) < 2 or len(value) > 34 or value.lower() in GENERIC
            or SENSITIVE.search(value) or FORBIDDEN.search(value)):
        return ""
    if value.startswith("on") and len(value) > 4:
        return ""
    return value


def infer_fields(files):
    counts = {}
    sources = {}
    sensitive_fields = set()
    for path in files:
        text = read_text(path)
        for pattern in FIELD_PATTERNS:
            for match in pattern.finditer(text, re.M):
                raw_field = re.sub(r"\s+", "", str(match.group(1))).strip("_'`\" ")
                if raw_field and SENSITIVE.search(raw_field):
                    sensitive_fields.add(raw_field)
                field = clean_field(raw_field)
                if not field:
                    continue
                counts[field] = counts.get(field, 0) + 1
                sources.setdefault(field, str(path))
    fields = sorted(counts, key=lambda x: (-counts[x], x.lower()))
    return fields[:60], sources, sorted(sensitive_fields)


def load_spec(path):
    if not path or not Path(path).exists():
        return {"pages": []}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"pages": []}
    except (OSError, json.JSONDecodeError):
        return {"pages": []}


def project_label(repo, project_name):
    raw = (project_name or repo.name).strip()
    raw = re.sub(r"[（(].*?[）)]", "", raw)
    raw = re.sub(r"(?:系统|平台|软件|项目)$", "", raw).strip()
    raw = FORBIDDEN.sub("", raw).strip()
    return raw or "业务"


def field_kind(field):
    key = field.lower()
    if re.search(r"(?:code|no|number|编号|编码|单号)", key):
        return "code"
    if re.search(r"(?:desc|remark|content|summary|description|说明|描述|备注|内容)", key):
        return "description"
    if re.search(r"(?:date|time|at|日期|时间|时间点)", key):
        return "date"
    if re.search(r"(?:amount|price|fee|money|total|金额|价格|费用|数量|count|num)", key):
        return "number"
    if re.search(r"(?:phone|mobile|tel|电话|手机)", key):
        return "phone"
    if re.search(r"(?:url|link|website|地址|链接)", key):
        return "url"
    if re.search(r"(?:status|state|阶段|状态)", key):
        return "status"
    if re.search(r"(?:person|owner|manager|contact|负责人|联系人|姓名|名称|name|title)", key):
        return "name"
    return "text"


def value_for(field, label, index, module_names):
    kind = field_kind(field)
    suffix = f"{index:02d}"
    module = module_names[(index - 1) % len(module_names)] if module_names else "业务事项"
    if kind == "code":
        return f"{label[:4].upper()}-{date.today().strftime('%Y%m')}-{index:03d}"
    if kind == "description":
        return f"围绕{module}记录业务安排、处理进度和结果，便于后续查看与跟进。"
    if kind == "date":
        return (date.today() - timedelta(days=index * 3)).isoformat()
    if kind == "number":
        return [12, 28, 56, 128][(index - 1) % 4]
    if kind == "phone":
        return f"13800138{index:03d}"
    if kind == "url":
        return f"https://example.com/{label[:8]}/{index}"
    if kind == "status":
        return ["待处理", "进行中", "已完成"][((index - 1) % 3)]
    if kind == "name":
        return f"{label}{module}{suffix}"
    return f"{label}{module}{suffix}"


def safe_value(value):
    return not FORBIDDEN.search(str(value))


def build_plan(repo, project_name, spec, records):
    files = scan_files(repo)
    fields, sources, sensitive = infer_fields(files)
    pages = [p for p in spec.get("pages", []) if isinstance(p, dict)]
    modules = [FORBIDDEN.sub("", str(p.get("module", "")).strip()).strip()
               for p in pages if str(p.get("module", "")).strip()]
    modules = [m or "业务事项" for m in modules]
    label = project_label(repo, project_name)
    fields = [f for f in fields if not SENSITIVE.search(f)]
    if not fields:
        fields = ["业务名称", "业务说明", "状态", "创建日期"]
    records_out = []
    for index in range(1, records + 1):
        values = {field: value_for(field, label, index, modules) for field in fields[:18]}
        values = {k: v for k, v in values.items() if safe_value(v)}
        records_out.append({"record_no": index, "values": values})
    scenarios = []
    for page in pages[:30]:
        scenarios.append({
            "module": page.get("module", ""),
            "entry": page.get("entry", ""),
            "fields_to_fill": [x for x in page.get("elements", []) if not FORBIDDEN.search(str(x))][:12],
            "suggested_record": ((len(scenarios) % records) + 1) if records else 1,
        })
    return {
        "project": project_name or repo.name,
        "generated": date.today().isoformat(),
        "source_files_scanned": len(files),
        "safety": {
            "synthetic_only": True,
            "forbidden_placeholder_terms": ["测试", "test", "demo", "mock", "示例"],
            "sensitive_fields_skipped": sensitive,
            "write_policy": "只允许通过本地项目 API 或浏览器/Computer Use 写入；禁止直接连接生产数据库。",
        },
        "fields": [{"name": f, "source": sources.get(f, "规则兜底"), "kind": field_kind(f)} for f in fields],
        "records": records_out,
        "screen_scenarios": scenarios,
        "execution": {
            "preferred": "browser_or_computer_use",
            "alternative": "project_local_api",
            "before_screenshot": "启动项目后逐条创建并核对页面反馈，再执行 capture.py",
            "rollback": "记录创建接口返回的业务编号，截图完成后按项目删除接口回滚",
        },
    }


def render_markdown(plan):
    lines = [
        f"# {plan['project']} 演示数据方案", "",
        f"> 生成日期：{plan['generated']}；扫描源码文件：{plan['source_files_scanned']} 个",
        "> 数据为结合项目字段生成的合成业务数据，不使用“测试/示例/demo”等占位词。",
        "> 写入时优先使用项目本地接口或浏览器/Computer Use，禁止直连生产数据库。", "",
        "## 数据字段", "", "| 字段 | 类型 | 来源 |", "| --- | --- | --- |",
    ]
    for field in plan["fields"]:
        lines.append(f"| {field['name']} | {field['kind']} | `{field['source']}` |")
    lines += ["", "## 记录样本", "", "| 编号 | 字段值 |", "| --- | --- |"]
    for record in plan["records"]:
        values = "；".join(f"{k}：{v}" for k, v in record["values"].items())
        lines.append(f"| {record['record_no']} | {values} |")
    lines += ["", "## 截图前操作", "", "1. 启动前后端并确认使用本地环境。",
              "2. 按 `screen_scenarios` 中的入口，在页面内创建对应记录。",
              "3. 记录接口返回的业务编号，截图完成后可按编号回滚。",
              "4. 核对页面显示内容与源码功能一致，再整理截图清单。", ""]
    if plan["safety"]["sensitive_fields_skipped"]:
        lines += ["## 已跳过的敏感字段", "", "、".join(plan["safety"]["sensitive_fields_skipped"]), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="结合项目源码生成软著截图用演示数据方案")
    parser.add_argument("--repo", required=True, help="项目源码目录")
    parser.add_argument("--project-name", default="", help="软件名称，用于生成业务语义")
    parser.add_argument("--spec", help="说明书素材.json，用于关联页面和字段")
    parser.add_argument("--records", type=int, default=3, help="生成记录数（默认 3）")
    parser.add_argument("--out", help="JSON 方案路径；默认写入 repo/soft-copyright-materials/演示数据方案.json")
    args = parser.parse_args()
    if args.records < 1 or args.records > 20:
        parser.error("--records 必须在 1 到 20 之间")
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        parser.error(f"项目目录不存在：{repo}")
    spec = load_spec(args.spec)
    plan = build_plan(repo, args.project_name, spec, args.records)
    out = Path(args.out).expanduser() if args.out else repo / "soft-copyright-materials" / "演示数据方案.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = out.with_name("演示数据方案.md")
    md.write_text(render_markdown(plan), encoding="utf-8")
    print(f"已生成：{out}")
    print(f"已生成：{md}")
    print("下一步：启动本地项目，按方案通过项目页面/API创建数据，再截图；未执行任何写库操作。")


if __name__ == "__main__":
    main()
