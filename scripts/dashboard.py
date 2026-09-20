#!/usr/bin/env python3
"""软著材料总览看板：一条命令扫描所有材料，生成一页 HTML，看清有几份、缺什么、哪里要改。

实时调用现有检查模块（aigc_check / copyright_check / oss_scrub），不依赖之前跑过的报告。
产出单文件 HTML（无外链、无 JS 依赖），双击就能看，也可以交给别人看。

用法：
  python3 dashboard.py --config soft-copyright-materials/ruanzhu.config.json --repo <项目目录>
  python3 dashboard.py --config ... --repo ... --out 看板.html --json 看板.json
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aigc_check import HIGH, LOW, analyze  # noqa: E402
from copyright_check import Findings, check_materials, check_project, check_sources  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]


def pdf_pages(path):
    try:
        from aigc_rules import pdf_text
        return pdf_text(path).count("\f") + 1 if path.exists() else 0
    except Exception:
        return 0


def count_pages(path):
    if not path.exists():
        return 0
    try:
        data = path.read_bytes()
        hits = re.findall(rb"/Type\s*/Page[^s]", data)
        if hits:
            return len(hits)
        m = re.search(rb"/Count\s+(\d+)", data)
        return int(m.group(1)) if m else 0
    except OSError:
        return 0


def cmd(script, args):
    return f"python3 {SKILL}/scripts/{script} {args}"


def scan_project(root, cfg, proj, cfg_path, repo):
    d = root / proj["id"]
    manual_md = d / "软件说明书.md"
    apply_md = d / "申请表填报文案.md"
    af = d / "auto-fill" / "config.json"
    src_docx = sorted((d / "源程序提取").glob("源程序鉴别材料-*.docx")) if (d / "源程序提取").exists() else []
    src_pdf = sorted((d / "源程序提取").glob("源程序鉴别材料-*.pdf")) if (d / "源程序提取").exists() else []
    manual_pdf = next((p for p in [d / "软件说明书.pdf", d / "软件文档.pdf"] if p.exists()), d / "软件说明书.pdf")
    shots = json.loads((d / "截图清单.json").read_text(encoding="utf-8")) if (d / "截图清单.json").exists() else {}

    info = {
        "id": proj["id"], "name": proj.get("name", proj["id"]), "version": proj.get("version", "V1.0"),
        "holder": cfg.get("copyright_holder", ""), "dev_date": cfg.get("development_completed_date", ""),
        "publish": cfg.get("first_publication_date", "未发表"),
        "files": [], "metrics": {}, "todos": [], "aigc": None, "chapters": [], "issues": [],
    }

    for label, path, note in [
        ("说明书 Markdown", manual_md, "正文来源"),
        ("说明书 PDF", manual_pdf, "提交件"),
        ("申请表填报文案", apply_md, "对照填表"),
        ("填表配置", af, "auto-fill.js 用"),
        ("源程序 DOCX", src_docx[0] if src_docx else d / "源程序提取" / "源程序鉴别材料.docx", "编辑稿"),
        ("源程序 PDF", src_pdf[0] if src_pdf else d / "源程序提取" / "源程序鉴别材料.pdf", "提交件"),
    ]:
        info["files"].append({"label": label, "ok": path.exists(), "path": str(path.relative_to(root)) if path.exists() else "—",
                              "note": note})

    form = json.loads(af.read_text(encoding="utf-8")) if af.exists() else {}
    flat = {k: v for sec in form.values() if isinstance(sec, dict) for k, v in sec.items()}
    todo_fields = [k for k, v in flat.items() if isinstance(v, str) and re.search(r"【[^】]*】", v)]
    main_len = len(re.sub(r"\s", "", str(flat.get("mainFunction", ""))))
    info["form"] = {"exists": bool(form), "todo_fields": todo_fields, "main_len": main_len,
                    "total": len(flat)}
    text = manual_md.read_text(encoding="utf-8") if manual_md.exists() else ""
    info["metrics"] = {
        "说明书字数": len(re.sub(r"\s", "", text)),
        "说明书章节": len(re.findall(r"(?m)^# ", text)),
        "说明书页数": count_pages(manual_pdf),
        "源程序页数": count_pages(src_pdf[0]) if src_pdf else 0,
        "截图": shots.get("count", 0),
        "取材文件": len(proj.get("source_files", [])),
        "申请表字段": f"{info['form']['total'] - len(info['form']['todo_fields'])}/{info['form']['total']}" if info["form"]["exists"] else "未生成",
    }

    if manual_md.exists():
        a = analyze(manual_md)
        info["aigc"] = {"score": a["score"], "grade": a["grade"], **a["distribution"],
                        "placeholders": a["stats"]["placeholders"], "op_ratio": a["stats"]["op_ratio"]}
        info["chapters"] = a["chapters"]
        info["issues"] = [{"kind": "AIGC", "sev": "high" if i["score"] >= HIGH else "medium",
                           "where": f"{i['chapter']} L{i['line']}", "what": "；".join(i["reasons"][:2]),
                           "text": i["text"][:80]} for i in a["issues"][:12]]
    return info


def build(cfg_path, repo, cfg):
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    projects = [scan_project(root, cfg, p, cfg_path, repo) for p in cfg["projects"]]

    F = Findings()
    check_project(repo, cfg, F)
    check_sources(repo, cfg, F)
    check_materials(root, cfg, F)
    own_files = {pr["id"]: set(cfg_p.get("source_files", []))
                 for pr, cfg_p in zip(projects, cfg["projects"])}
    for p in projects:
        for item in F.items:
            f = item["where"].split(":")[0]
            mine = (item["layer"] == "项目"                      # 项目层对所有软著都成立
                    or (item["layer"] == "取材" and f in own_files[p["id"]])
                    or p["id"] in item["where"])                # 产出层按材料目录归属
            if mine:
                p["issues"].append({"kind": f"版权·{item['layer']}", "sev": item["severity"],
                                    "where": item["where"], "what": item["rule"], "text": item["advice"]})
    # 待办：按“现在该做什么”排序
    for p in projects:
        a, m = p["aigc"], p["metrics"]
        hi = sum(1 for i in p["issues"] if i["sev"] == "high")
        if not (root / p["id"] / "软件说明书.md").exists():
            p["todos"].append(("high", "说明书还没生成", cmd("generate_docs.py", f"--config {cfg_path}")))
        if a and a["placeholders"]:
            p["todos"].append(("high", f"说明书还有 {a['placeholders']} 处占位符没填",
                               "读源码补真实内容；素材见 说明书素材.json"))
        if a and a["score"] >= LOW:
            p["todos"].append(("high" if a["score"] >= HIGH else "medium",
                               f"AIGC {a['score']} 分（{a['grade']}），需改写",
                               cmd("aigc_rewrite.py", f"{root / p['id']} --apply")))
        if hi:
            p["todos"].append(("high", f"版权风险高危 {hi} 条", cmd("copyright_check.py", f"--config {cfg_path} --repo {repo} --fail-on high")))
        f = p.get("form", {})
        if not f.get("exists"):
            p["todos"].append(("high", "申请表字段未生成", cmd("application_form.py", f"--config {cfg_path}")))
        elif f["todo_fields"]:
            p["todos"].append(("high", f"申请表还有 {len(f['todo_fields'])} 个字段没填：{('、'.join(f['todo_fields'][:6]))}",
                               "在 ruanzhu.config.json 补 env / dev_purpose 等字段后重跑 application_form.py"))
        elif not 500 <= f["main_len"] <= 1300:
            p["todos"].append(("high", f"申请表“主要功能”{f['main_len']} 字，需 500–1300 字",
                               "补完说明书功能模块章节后重跑 application_form.py"))
        else:
            p["todos"].append(("low", f"申请表字段齐全（主要功能 {f['main_len']} 字），可以填表",
                               cmd("form_plan.py", f"--config {root / p['id'] / 'auto-fill' / 'config.json'} "
                                                   f"--out {root / p['id'] / '填表操作计划.md'}")
                               + "，然后让 Claude 用浏览器插件按计划填写并保存草稿"))
        if not m["截图"]:
            p["todos"].append(("low", "没有截图，说明书保留占位文字",
                               cmd("screenshots.py", f"--materials {root / p['id']}")))
        if not m["说明书页数"]:
            p["todos"].append(("medium", "说明书 PDF 未渲染", cmd("render_pdfs.py", f"--config {cfg_path}")))
        elif m["说明书页数"] < 40:
            p["todos"].append(("low", f"说明书仅 {m['说明书页数']} 页，通常 50–80 页", "补充功能章节的操作步骤与截图"))
        if not m["源程序页数"]:
            p["todos"].append(("medium", "源程序 PDF 未生成",
                               cmd("generate_source_docx.py", f"--config {cfg_path} --repo {repo}") + " && " + cmd("render_pdfs.py", f"--config {cfg_path}")))
        elif m["源程序页数"] < 60:
            p["todos"].append(("high", f"源程序只有 {m['源程序页数']} 页，不足 60 页", "在 config 补选自研文件后重新提取"))
        p["ready"] = not any(t[0] == "high" for t in p["todos"])
    return projects, F


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#111827;--mut:#6b7280;--line:#e5e7eb;--hi:#dc2626;--mid:#d97706;--low:#2563eb;--ok:#059669}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e5e7eb;--mut:#9ca3af;--line:#2a2f3a}}
*{box-sizing:border-box}body{margin:0;padding:24px 16px 60px;background:var(--bg);color:var(--fg);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1100px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);font-size:13px;margin-bottom:20px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-bottom:24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.stat b{display:block;font-size:26px;line-height:1.2}.stat span{color:var(--mut);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
.head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;justify-content:space-between;margin-bottom:12px}
.head h2{font-size:17px;margin:0}.meta{color:var(--mut);font-size:12px}
.badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600;color:#fff}
.b-ok{background:var(--ok)}.b-hi{background:var(--hi)}.b-mid{background:var(--mid)}.b-low{background:var(--low)}
table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0 14px}
th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px}
.m{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:12px}.m div{font-size:13px}.m b{font-size:17px;display:block}
code{background:rgba(127,127,127,.14);padding:2px 6px;border-radius:5px;font-size:12px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
.todo{border-left:3px solid var(--line);padding:6px 0 6px 12px;margin:8px 0}
.todo.high{border-color:var(--hi)}.todo.medium{border-color:var(--mid)}.todo.low{border-color:var(--low)}
.bar{height:7px;border-radius:4px;background:var(--line);overflow:hidden;display:flex;margin-top:6px}
.bar i{display:block;height:100%}details summary{cursor:pointer;color:var(--mut);font-size:13px;margin:6px 0}
.foot{color:var(--mut);font-size:12px;margin-top:24px}
"""


def esc(x):
    return html.escape(str(x))


def render(projects, F, cfg, cfg_path):
    total_hi = F.count("high")
    ready = sum(1 for p in projects if p["ready"])
    out = [f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>软著材料看板</title><style>{CSS}</style></head>
<body><div class="wrap"><h1>软著材料看板</h1>
<div class="sub">著作权人 {esc(cfg.get('copyright_holder', '【未填】'))}　｜　发表状态 {esc(cfg.get('first_publication_date', '未发表'))}
　｜　配置 <code>{esc(cfg_path)}</code>　｜　{datetime.now():%Y-%m-%d %H:%M} 扫描</div>
<div class="grid">
<div class="stat"><b>{len(projects)}</b><span>份软著</span></div>
<div class="stat"><b style="color:var(--{'ok' if ready == len(projects) else 'hi'})">{ready}/{len(projects)}</b><span>可进入提交</span></div>
<div class="stat"><b style="color:var(--{'hi' if total_hi else 'ok'})">{total_hi}</b><span>版权高危</span></div>
<div class="stat"><b>{sum(p['metrics']['说明书页数'] for p in projects)}</b><span>说明书总页数</span></div>
<div class="stat"><b>{sum(p['metrics']['截图'] for p in projects)}</b><span>截图</span></div>
</div>"""]

    for p in projects:
        a = p["aigc"] or {}
        badge = ('<span class="badge b-ok">可提交</span>' if p["ready"]
                 else '<span class="badge b-hi">待处理</span>')
        out.append(f"""<div class="card"><div class="head">
<h2>{esc(p['name'])} <span class="meta">{esc(p['version'])}　{esc(p['id'])}</span></h2>{badge}</div>
<div class="meta">开发完成 {esc(p['dev_date'] or '【未填】')}　｜　发表状态 {esc(p['publish'])}</div>
<div class="m">""")
        for k, v in p["metrics"].items():
            out.append(f"<div><b>{v}</b>{esc(k)}</div>")
        if a:
            color = "ok" if a["score"] < LOW else ("mid" if a["score"] < HIGH else "hi")
            out.append(f"""<div><b style="color:var(--{color})">{a['score']}</b>AIGC 分（{esc(a['grade'])}）</div>
<div><b>{a['op_ratio']:.0%}</b>操作句占比</div>""")
        out.append("</div>")
        if a:
            out.append(f"""<div class="bar"><i style="width:{a['human']}%;background:var(--ok)"></i>
<i style="width:{a['suspect']}%;background:var(--mid)"></i><i style="width:{a['ai']}%;background:var(--hi)"></i></div>
<div class="meta">人工 {a['human']}%　疑似 {a['suspect']}%　AI {a['ai']}%　｜　占位符 {a['placeholders']} 处</div>""")

        if p["todos"]:
            out.append("<h3 style='font-size:14px;margin:16px 0 4px'>下一步</h3>")
            order = {"high": 0, "medium": 1, "low": 2}
            for sev, title, how in sorted(p["todos"], key=lambda t: order[t[0]]):
                how_html = f"<code>{esc(how)}</code>" if how.startswith("python3") else esc(how)
                out.append(f'<div class="todo {sev}"><b>{esc(title)}</b><br>{how_html}</div>')
        else:
            out.append('<div class="todo low"><b>没有待办：材料齐全，可进入填表</b></div>')

        out.append("<table><tr><th>材料</th><th>状态</th><th>路径</th><th>用途</th></tr>")
        for f in p["files"]:
            mark = '<span style="color:var(--ok)">已生成</span>' if f["ok"] else '<span style="color:var(--hi)">缺失</span>'
            out.append(f"<tr><td>{esc(f['label'])}</td><td>{mark}</td><td><code>{esc(f['path'])}</code></td><td>{esc(f['note'])}</td></tr>")
        out.append("</table>")

        if p["chapters"]:
            out.append("<details><summary>分章节 AIGC 得分</summary><table><tr><th>章节</th><th>得分</th><th>块数</th></tr>")
            for c in p["chapters"]:
                col = "ok" if c["score"] < LOW else ("mid" if c["score"] < HIGH else "hi")
                out.append(f"<tr><td>{esc(c['chapter'])}</td><td style='color:var(--{col})'>{c['score']}</td><td>{c['blocks']}</td></tr>")
            out.append("</table></details>")

        if p["issues"]:
            hi = [i for i in p["issues"] if i["sev"] == "high"]
            out.append(f"<details open><summary>问题明细（高危 {len(hi)} / 共 {len(p['issues'])}）</summary>"
                       "<table><tr><th>类别</th><th>位置</th><th>问题</th><th>怎么改</th></tr>")
            for i in sorted(p["issues"], key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["sev"]])[:25]:
                col = {"high": "hi", "medium": "mid", "low": "low"}[i["sev"]]
                out.append(f"<tr><td><span class='badge b-{col}'>{esc(i['kind'])}</span></td>"
                           f"<td><code>{esc(i['where'])}</code></td><td>{esc(i['what'])}</td><td>{esc(i['text'])}</td></tr>")
            out.append("</table></details>")
        out.append("</div>")

    out.append(f"""<div class="foot">AIGC 分为本地启发式估计（&lt;{LOW} 低 / {LOW}-{HIGH} 中 / ≥{HIGH} 高），
不等同于商业检测结论；版权检查只做线索排查，不构成法律意见。重新扫描：
<code>python3 {SKILL}/scripts/dashboard.py --config {esc(cfg_path)} --repo &lt;项目目录&gt;</code></div>
</div></body></html>""")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="软著材料总览看板")
    ap.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    ap.add_argument("--repo", default=".", help="项目源码目录（版权检查用）")
    ap.add_argument("--out", help="HTML 输出路径（默认 <output_root>/看板.html）")
    ap.add_argument("--json", help="同时输出 JSON")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    projects, F = build(cfg_path, Path(args.repo).resolve(), cfg)
    out = Path(args.out) if args.out else root / "看板.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(projects, F, cfg, cfg_path), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps({"projects": projects, "findings": F.items},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
    todo = sum(len(p["todos"]) for p in projects)
    print(f"{len(projects)} 份软著，{sum(1 for p in projects if p['ready'])} 份可提交，待办 {todo} 项")
    print(out.resolve())


if __name__ == "__main__":
    main()
