#!/usr/bin/env python3
"""从项目源码抽取说明书素材，生成《说明书素材.json》+ 确认用的 Markdown 预览。

说明书写不好，多半是因为落笔时手上只有模块名。这个脚本把界面上真实存在的东西先挖出来：
页面文件、进入位置（路由/菜单）、界面控件文字、字段校验规则、提示语、错误码，
逐页整理成结构化素材，交用户确认后再写正文——对应 writing-style.md 的“操作动线优先”。

素材只来自源码，脚本不编造；抽不到的字段留空，由 Claude 读源码补、用户确认。

用法：
  python3 manual_spec.py --repo . --out soft-copyright-materials/说明书素材.json
  python3 manual_spec.py --repo . --out ... --max-pages 30 --include src/pages src/views
"""

import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

UI_EXT = {".vue", ".tsx", ".jsx", ".ts", ".js", ".wxml", ".axml", ".ttml", ".html", ".htm",
          ".dart", ".swift", ".kt", ".java", ".cs", ".xml", ".py", ".php", ".uvue"}
CODE_EXT = UI_EXT | {".go", ".rs", ".c", ".cc", ".cpp", ".h", ".m", ".mm", ".rb", ".scss", ".css", ".less", ".sql"}
SKIP_DIR = re.compile(
    r"(?:^|/)(?:node_modules|bower_components|vendor|third[_-]?party|dist|build|out|target|\.git|\.idea|\.vscode"
    r"|Pods|site-packages|__pycache__|coverage|\.next|\.nuxt|unpackage|uni_modules|miniprogram_npm|bin-debug|bin-release"
    r"|backups?|bak|archive|_workorders|artifacts|snapshots?|tmp|temp|examples?|samples?|demo|mock|__tests__|tests?|spec)/"
    r"|/\d{8}-\d{6}/", re.I)
# 内部工具/脚本目录：不是给最终用户看的界面
TOOL_DIR = re.compile(r"(?:^|/)(?:tools?|scripts?|build|gulp|webpack|devtools?|cli)/", re.I)
PAGE_DIR = re.compile(r"(?:^|/)(?:pages?|views?|screens?|activity|activities|fragments?|windows?|modules?|components?/pages)/", re.I)

CJK = r"[一-龥]"
# 界面文字：标签/按钮/占位符/标题属性，以及模板里的纯中文节点
ELEMENT_PATTERNS = [
    rf'(?:label|placeholder|title|text|btnText|confirmText|cancelText|tooltip|alt)\s*[:=]\s*[\'"`]([^\'"`\n]*{CJK}[^\'"`\n]*)',
    rf'>\s*([^<>{{}}\n]*{CJK}[^<>{{}}\n]*?)\s*<',
    rf'(?:Text|Button|MenuItem|TabItem|setTitle|setText)\s*\(\s*[\'"`]([^\'"`\n]*{CJK}[^\'"`\n]*)',
    rf'android:text\s*=\s*"([^"\n]*{CJK}[^"\n]*)"',
]
FEEDBACK_PATTERNS = [
    rf'(?:showToast|showModal|toast|Toast|message|Message|alert|Alert|notify|Notify|snackBar|tip|Tip|prompt)'
    rf'[^\n]{{0,40}}?[\'"`]([^\'"`\n]*{CJK}[^\'"`\n]*)',
    rf'[\'"`]((?:操作)?(?:成功|失败|已完成|已取消|已保存|已提交|已删除)[^\'"`\n]{{0,20}})[\'"`]',
]
VALIDATION_PATTERNS = [
    rf'[\'"`]([^\'"`\n]*(?:不能为空|必填|请输入|请选择|格式不正确|长度|至少|最多|不得超过|已存在|不一致)[^\'"`\n]*)[\'"`]',
    r'(?:maxlength|minlength|maxLength|minLength|max|min)\s*[:=]\s*[\'"`]?(\d{1,6})',
    r'(required)\s*[:=]\s*true',
    r'pattern\s*[:=]\s*/([^/\n]{3,40})/',
]
ERROR_PATTERNS = [
    rf'(?:code|errCode|errorCode|status|ret)\s*[=:]==?\s*[\'"]?(\d{{3,6}})[\'"]?[^\n]{{0,40}}?[\'"`]([^\'"`\n]*{CJK}[^\'"`\n]*)',
    rf'[\'"]?(\d{{3,6}})[\'"]?\s*[:,]\s*[\'"`]([^\'"`\n]*{CJK}[^\'"`\n]*)[\'"`]',
]
ROUTE_PATTERNS = [
    r'path\s*:\s*[\'"`]([^\'"`\n]+)[\'"`][^\n]{0,200}?(?:component|page)\s*[:=][^\n]{0,120}?[\'"`/]([\w.-]+)[\'"`)]',
    r'[\'"`](pages/[\w/-]+)[\'"`]',            # 小程序 app.json
    r'@(?:GetMapping|PostMapping|RequestMapping)\s*\(\s*[\'"]([^\'"\n]+)',
]
API_PATTERNS = [
    # Spring MVC / JAX-RS
    (r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*\(\s*["\']([^"\'\n]*)', "annotation"),
    (r'@(?:GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\']([^"\'\n]*)', "jaxrs"),
    # Express / Fastify / Koa style routers
    (r'\b(?:router|app|server)\.(get|post|put|delete|patch|options)\s*\(\s*["\']([^"\'\n]*)', "js"),
    # FastAPI / Flask
    (r'@(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\'\n]*)', "python"),
    # Go net/http and common routers
    (r'\.(GET|POST|PUT|DELETE|PATCH|Handle|HandleFunc)\s*\(\s*["\']([^"\'\n]*)', "go"),
]
TITLE_PATTERNS = [
    rf'(?:title|navigationBarTitleText|pageTitle)\s*[:=]\s*[\'"`]([^\'"`\n]*{CJK}[^\'"`\n]*)',
    rf'^\s*(?://|#|\*|<!--)\s*({CJK}{{2,20}})\s*(?:页面|界面|视图|模块|组件)?\s*$',
    rf'<title>\s*([^<\n]*{CJK}[^<\n]*)</title>',
]


def uniq(items, limit=None, clean=True):
    out = []
    for x in items:
        x = clean_ui_text(x) if clean else re.sub(r"\s+", " ", str(x)).strip()
        if not x or x in out:
            continue
        out.append(x)
    return out[:limit] if limit else out


def find_all(text, patterns, group=1):
    hits = []
    for p in patterns:
        for m in re.finditer(p, text, re.M):
            try:
                hits.append(m.group(group))
            except IndexError:
                continue
    return hits


def scan_files(repo, includes):
    files = []
    roots = [repo / i for i in includes] if includes else [repo]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            rel = str(p.relative_to(repo))
            if not p.is_file() or SKIP_DIR.search("/" + rel + "/") or p.stat().st_size > 800_000:
                continue
            if p.suffix.lower() in CODE_EXT:
                files.append(p)
    return files


def stats(repo, files):
    total, by_ext = 0, Counter()
    for p in files:
        try:
            n = sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        total += n
        by_ext[p.suffix.lower()] += n
    return {"source_files": len(files), "source_lines": total,
            "by_ext": dict(by_ext.most_common(12)),
            "note": "source_lines 为项目全部源码行数，申请表“源程序量”填这个数，不是取材行数"}


def route_map(repo, files):
    """路由文件 → {组件名或页面路径: 路由 path}，用于推断“进入位置”。"""
    routes = {}
    for p in files:
        if not re.search(r"rout|app\.json|pages\.json|menu|nav", p.name, re.I):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(ROUTE_PATTERNS[0], text, re.S):
            routes.setdefault(m.group(2), m.group(1))
        for m in re.finditer(ROUTE_PATTERNS[1], text):
            routes.setdefault(Path(m.group(1)).name, "/" + m.group(1))
    return routes


def extract_apis(repo, files):
    """从源码提取接口事实；只记录源码中出现的 method/path，不猜测运行结果。"""
    apis = []
    for path in files:
        if path.suffix.lower() not in CODE_EXT:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        base_path = ""
        # 类级别的 Spring @RequestMapping 作为路径前缀，仅在同一文件内拼接。
        if path.suffix.lower() in {".java", ".kt"}:
            m = re.search(r'@RequestMapping\s*\(\s*["\']([^"\'\n]*)', text)
            base_path = m.group(1).rstrip("/") if m else ""
        for pattern, kind in API_PATTERNS:
            for match in re.finditer(pattern, text, re.I | re.M):
                groups = match.groups()
                if kind == "annotation":
                    method, route = groups[0].replace("Mapping", "").upper(), groups[1]
                    if method == "REQUEST":
                        # 类级别 @RequestMapping 只作为前缀，不当作一个可调用接口。
                        continue
                elif kind == "jaxrs":
                    method, route = "HTTP", groups[0]
                else:
                    method, route = groups[0].upper(), groups[1]
                route = (base_path + "/" + route.lstrip("/")).replace("//", "/") or "/"
                line = text.count("\n", 0, match.start()) + 1
                item = {"method": method, "path": route, "file": str(path.relative_to(repo)), "line": line}
                if item not in apis:
                    apis.append(item)
    return sorted(apis, key=lambda x: (x["path"], x["method"], x["file"]))


def backend_detected(files, apis):
    if apis:
        return True
    names = " ".join(str(p).lower() for p in files)
    return any(token in names for token in ("go.mod", "pom.xml", "build.gradle", "manage.py", "main.py", "application.yml", "application.yaml"))


def api_docs_enabled(files):
    """仅在源码/依赖配置出现文档组件时把 Knife4j/OpenAPI 证据列为必需。"""
    dependency_names = {"pom.xml", "build.gradle", "build.gradle.kts", "package.json", "requirements.txt", "pyproject.toml", "go.mod"}
    dependency_markers = ("knife4j", "springdoc", "swagger-ui", "swaggerui", "swagger", "openapi")
    source_markers = ("@openapidefinition", "@operation", "@swagger", "swaggerui", "swagger-ui")
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        config_file = path.name.lower().startswith("application") and path.suffix.lower() in {".yml", ".yaml", ".properties", ".json"}
        if ((path.name.lower() in dependency_names and any(marker in text for marker in dependency_markers))
                or (config_file and any(marker in text for marker in ("springdoc", "knife4j", "swagger")))
                or any(marker in text for marker in source_markers)):
            return True
    return False


def evidence_plan(backend, apis, docs_enabled=False):
    if not backend:
        return []
    first = apis[0] if apis else None
    suffix = f"（优先使用 {first['method']} {first['path']}）" if first else "（选择源码中真实存在的接口）"
    return [
        {"id": "api-docs", "title": "Knife4j/OpenAPI 接口文档页", "required": docs_enabled,
         "note": "项目已检测到文档组件，需采集真实调试页" if docs_enabled else "未检测到文档组件；如项目实际启用，请在确认后补采集"},
        {"id": "api-success", "title": "真实接口成功请求与 JSON 响应", "required": True,
         "note": f"使用源码接口和真实业务字段{suffix}，脱敏后截图"},
        {"id": "api-error", "title": "参数校验失败或 HTTP 4xx 返回", "required": True,
         "note": "使用项目真实校验规则触发，保留状态码和错误响应"},
        {"id": "runtime-log", "title": "启动日志与业务请求日志", "required": True,
         "note": "截取项目真实 stdout/日志文件，不补写日志内容"},
    ]


def clean_ui_text(s):
    """去掉 HTML 标签碎片、转义符和富文本残留。"""
    s = re.sub(r"<[^>]*>?|\\[nrt]|&[a-z]+;", " ", str(s))
    s = re.sub(r"\s+", " ", s).strip(" ：:，,。.、|-=")
    return s if 1 < len(s) <= 24 and not re.search(r"[<>{}$]|color\s*=|^\d+$", s) else ""


VERBY = re.compile(r"^(?:为|设置|请求|更新|获取|初始化|刷新|显示|展示|购买|处理|判断|检查|计算|添加|删除|返回|有|是否|当前)")


def page_title(text, path, elements=None):
    """优先界面上真实出现的标题文字，其次注释短词，最后文件名。"""
    for t in find_all(text, TITLE_PATTERNS[:1] + TITLE_PATTERNS[2:]):   # 显式标题属性 / <title> 最优先
        t = clean_ui_text(t)
        if t:
            return t
    for e in (elements or [])[:2]:                                       # 其次：界面上第一条文字
        if 2 <= len(e) <= 8 and not VERBY.match(e) and not re.search(r"[：:，,。]", e):
            return e
    for t in find_all(text, TITLE_PATTERNS[1:2]):                        # 注释首行：只收短词
        t = clean_ui_text(t)
        if t and len(t) <= 8 and not VERBY.match(t) and not re.search(r"[，。,.；;、和与的]", t):
            return t
    return path.stem


def page_entry(path, routes):
    for key, val in routes.items():
        if key and (key == path.stem or key in str(path)):
            return val
    parent = path.parent.name
    return f"{parent}/{path.stem}" if parent else path.stem


def extract_page(repo, path, routes):
    text = path.read_text(encoding="utf-8", errors="ignore")
    elements = uniq(find_all(text, ELEMENT_PATTERNS), 12)
    feedbacks = uniq(find_all(text, FEEDBACK_PATTERNS), 8)
    validations = uniq(find_all(text, VALIDATION_PATTERNS[:1]), 8, clean=False)
    limits = uniq([m.group(0).strip() for pat in VALIDATION_PATTERNS[1:] for m in re.finditer(pat, text)], 6, clean=False)
    errors = []
    for pat in ERROR_PATTERNS:
        for m in re.finditer(pat, text):
            errors.append([m.group(1), clean_ui_text(m.group(2))])
    seen, err_uniq = set(), []
    for code, msg in errors:
        if code in seen or not msg:
            continue
        seen.add(code)
        err_uniq.append([code, msg])
    return {
        "module": page_title(text, path, elements),
        "file": str(path.relative_to(repo)),
        "lines": text.count("\n") + 1,
        "entry": page_entry(path, routes),
        "elements": elements,
        "validations": validations + limits,
        "feedbacks": feedbacks,
        "errors": err_uniq[:8],
        "steps": [],
        "purpose": "",
        "scope_note": "",
        "screenshot": "",
    }


def score(page):
    """界面证据越多越像真正要写进说明书的页面。"""
    s = (len(page["elements"]) * 2 + len(page["feedbacks"]) * 2 + len(page["validations"])
         + len(page["errors"]) * 2 + (3 if PAGE_DIR.search("/" + page["file"]) else 0))
    return s - 6 if TOOL_DIR.search("/" + page["file"]) else s      # 内部工具页排后面


def preview(spec):
    out = [f"# {spec['project']} 说明书素材（{spec['generated']}）", "",
           f"> 源码规模：{spec['stats']['source_files']} 个文件 / {spec['stats']['source_lines']} 行"
           f"（申请表“源程序量”填 {spec['stats']['source_lines']}）", "",
           "> 下表来自源码扫描，**未经确认不要直接写进说明书**：核对模块名和进入位置是否与实际界面一致，",
           "> 补上 purpose（这个页面解决什么）、steps（操作顺序）、scope_note（不负责的范围），再生成正文。", "",
           "| # | 模块 | 进入位置 | 源码 | 界面文字 | 校验/限制 | 提示语 | 错误码 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, p in enumerate(spec["pages"], 1):
        out.append(f"| {i} | {p['module']} | `{p['entry']}` | `{p['file']}`（{p['lines']} 行） "
                   f"| {'、'.join(p['elements'][:6]) or '—'} | {'；'.join(p['validations'][:3]) or '—'} "
                   f"| {'；'.join(p['feedbacks'][:3]) or '—'} "
                   f"| {'；'.join(f'{c} {m}' for c, m in p['errors'][:3]) or '—'} |")
    thin = [p["module"] for p in spec["pages"] if score(p) < 4]
    if thin:
        out += ["", f"界面证据偏少的模块（写正文前需人工补充或改选文件）：{'、'.join(thin[:10])}"]
    if spec.get("backend"):
        out += ["", "## 后端证据计划", "", "> 以下证据必须来自真实运行或调试结果，不能用模板文字代替。", "",
                "| ID | 证据 | 采集说明 |", "|---|---|---|"]
        for item in spec.get("evidence_plan", []):
            out.append(f"| {item['id']} | {item['title']} | {item['note']} |")
        if spec.get("apis"):
            out += ["", "### 源码接口清单", "", "| 方法 | 路径 | 源码 | 行号 |", "|---|---|---|---|"]
            for api in spec["apis"][:40]:
                out.append(f"| {api['method']} | `{api['path']}` | `{api['file']}` | {api['line']} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="抽取说明书素材")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="soft-copyright-materials/说明书素材.json")
    ap.add_argument("--include", nargs="*", default=[], help="只扫描这些子目录（默认全项目）")
    ap.add_argument("--max-pages", type=int, default=25, help="保留界面证据最多的前 N 个页面")
    ap.add_argument("--project-name", default="")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    files = scan_files(repo, args.include)
    if not files:
        raise SystemExit(f"{repo} 下没有扫描到源码文件")
    routes = route_map(repo, files)
    apis = extract_apis(repo, files)
    backend = backend_detected(files, apis)
    docs_enabled = api_docs_enabled(files)
    candidates = [p for p in files if p.suffix.lower() in UI_EXT]
    pages = [extract_page(repo, p, routes) for p in candidates]
    pages = [p for p in pages if score(p) > 0]
    # 同一页面的多份副本（备份目录等）只留路径最短的一份
    best = {}
    for p in pages:
        key = (p["module"], tuple(p["elements"][:5]))
        if key not in best or len(p["file"]) < len(best[key]["file"]):
            best[key] = p
    pages = list(best.values())
    pages.sort(key=score, reverse=True)
    pages = pages[: args.max_pages]
    pages.sort(key=lambda p: p["entry"])

    spec = {
        "project": args.project_name or repo.name,
        "generated": date.today().isoformat(),
        "repo": str(repo),
        "stats": stats(repo, files),
        "routes_found": len(routes),
        "backend": backend,
        "apis": apis,
        "evidence_plan": evidence_plan(backend, apis, docs_enabled),
        "pages": pages,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out.with_name(out.stem + "预览.md")
    md.write_text(preview(spec), encoding="utf-8")
    print(f"{out}（{len(pages)} 个页面 / 共 {spec['stats']['source_lines']} 行源码）")
    print(md)


if __name__ == "__main__":
    main()
