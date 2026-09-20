#!/usr/bin/env python3
"""申请表字段集中整理：一处生成，三处一致（填表配置 / 填报文案 / 校验清单）。

R11 申请表的字段散在 config、说明书、源码统计里，手工誊抄最容易出错。这个脚本把它们
收敛成一份 `auto-fill/config.json`（auto-fill.js 直接用）和一份《申请表填报文案.md》
（人工对照官网填时用），并逐字段校验长度、格式、必填和一致性。

字段来源：
  软件全称/简称/版本/分类  ← ruanzhu.config.json 的 projects[]
  著作权人/开发完成日期/发表状态 ← ruanzhu.config.json 顶层（发表状态默认“未发表”）
  源程序量                ← 说明书素材.json 的全项目源码行数（不是取材行数）
  编程语言                ← 说明书素材.json 的 by_ext 统计
  开发/运行环境           ← ruanzhu.config.json 的 env 字段，缺了就留占位并在校验里报出来
  软件主要功能            ← 说明书“功能模块”章节，按模块拼成 500–1300 字初稿
  两份 PDF                ← 材料目录里实际存在的文件

脚本不编造：拿不到的字段写【待填写：…】，并在校验清单里列为待办。

用法：
  python3 application_form.py --config soft-copyright-materials/ruanzhu.config.json
  python3 application_form.py --config ... --strict      # 有未通过项时退出码 1
"""

import argparse
import json
import re
import sys
from pathlib import Path

LIMITS = {  # 官网字段长度上限（mainFunction 为区间）
    "softwareName": 60, "shortName": 15, "version": 20, "devTools": 50, "devOS": 50, "runOS": 50,
    "devHardware": 100, "runHardware": 100, "runSupport": 50, "languageOther": 50,
    "devPurpose": 50, "targetIndustry": 50, "techFeatureText": 100,
}
MAIN_MIN, MAIN_MAX = 500, 1300
EXT_LANG = {
    ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".vue": "JavaScript",
    ".java": "Java", ".kt": "Kotlin", ".py": "Python", ".go": "Go", ".rs": "Rust", ".php": "PHP",
    ".cs": "C#", ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".m": "Objective-C", ".swift": "Swift",
    ".dart": "Dart", ".rb": "Ruby", ".sql": "SQL", ".wxml": "JavaScript", ".scss": "CSS", ".less": "CSS", ".css": "CSS",
}
PLACEHOLDER = re.compile(r"【[^】]*】")


def chars(s):
    return len(re.sub(r"\s", "", str(s or "")))


def load(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def languages(spec):
    """按行数排序的语言清单：主语言 + 其他。"""
    if not spec:
        return "【待填写：主要编程语言】", ""
    agg = {}
    for ext, n in spec["stats"].get("by_ext", {}).items():
        lang = EXT_LANG.get(ext)
        if lang:
            agg[lang] = agg.get(lang, 0) + n
    ranked = [l for l, _ in sorted(agg.items(), key=lambda x: -x[1])]
    return (ranked[0] if ranked else "【待填写：主要编程语言】"), "、".join(ranked[1:4])


def main_function_draft(manual_md, project):
    """从说明书“功能模块”章节拼主要功能初稿：模块名 + 功能说明 + 首条操作步骤。"""
    if not manual_md.exists():
        return ""
    text = manual_md.read_text(encoding="utf-8")
    body = text[text.find("\n# 功能模块"):] if "\n# 功能模块" in text else ""
    body = body[: body.find("\n# 运维管理")] if "\n# 运维管理" in body else body
    parts = []
    for m in re.finditer(r"(?m)^## 7\.\d+ (.+?)$(.*?)(?=^## |\Z)", body, re.S):
        name, sec = m.group(1).strip(), m.group(2)
        if name == "模块一览":
            continue
        desc = re.search(r"（一）功能说明\s*\n+(.+?)(?=\n\n|（二）)", sec, re.S)
        step = re.search(r"(?m)^1\.\s*(.+)$", sec)
        desc_t = PLACEHOLDER.sub("", desc.group(1)).strip() if desc else ""
        step_t = PLACEHOLDER.sub("", step.group(1)).strip() if step else ""
        line = f"{name}：{desc_t}" if desc_t else f"{name}："
        if step_t:
            line += f"用户{step_t}"
        parts.append(re.sub(r"\s+", "", line).rstrip("。") + "。")
    draft = "".join(parts)
    return draft[:MAIN_MAX]


def build(cfg, project, root, spec, args):
    d = root / project["id"]
    env = {**cfg.get("env", {}), **project.get("env", {})}
    lang, lang_other = languages(spec)
    src_pdf = sorted((d / "源程序提取").glob("源程序鉴别材料-*.pdf"))
    doc_pdf = next((p for p in [d / "软件说明书.pdf", d / "软件文档.pdf"] if p.exists()), None)
    main_fn = project.get("main_function") or main_function_draft(d / "软件说明书.md", project)

    return {
        "_source": "application_form.py 生成，勿手工改；改 ruanzhu.config.json 后重跑",
        "_project": project["id"],
        "step1_identity": {
            "applicantRole": cfg.get("applicant_role", "我是申请人"),
            "applicantType": cfg.get("applicant_type", "企业法人"),
            "developType": cfg.get("develop_type", "独立开发"),
            "acquireType": cfg.get("acquire_type", "原始取得"),
        },
        "step2_basic": {
            "softwareName": project["name"],
            "shortName": project.get("short_name", project["name"][:15]),
            "version": project.get("version", "V1.0"),
            "category": project.get("category", "应用软件"),
            "completionDate": cfg.get("development_completed_date", "【待填写：开发完成日期 YYYY-MM-DD】"),
            "published": False,
            "copyrightHolder": cfg.get("copyright_holder", "【待填写：著作权人全称】"),
        },
        "step3_dev": {
            "devHardware": env.get("dev_hardware", "【待填写：开发硬件环境】"),
            "runHardware": env.get("run_hardware", "【待填写：运行硬件环境】"),
            "devOS": env.get("dev_os", "【待填写：开发操作系统】"),
            "devTools": env.get("dev_tools", "【待填写：开发工具，写 IDE/编译器/构建工具，不写框架名】"),
            "runOS": env.get("run_os", "【待填写：运行操作系统】"),
            "runSupport": env.get("run_support", "【待填写：运行支撑环境】"),
            "language": lang,
            "languageOther": lang_other,
            "sourceLines": str(spec["stats"]["source_lines"]) if spec else "【待填写：全项目源码行数】",
        },
        "step4_features": {
            "devPurpose": project.get("dev_purpose", "【待填写：开发目的，50 字内】"),
            "targetIndustry": project.get("target_industry", "【待填写：面向领域/行业，50 字内】"),
            "mainFunction": main_fn or "【待填写：软件主要功能，500-1300 字】",
            "techFeatureTag": project.get("tech_feature_tag", "应用软件"),
            "techFeatureText": project.get("tech_feature_text", "【待填写：技术特点关键词，100 字内】"),
            "programPdf": f"../源程序提取/{src_pdf[0].name}" if src_pdf else "【待生成：源程序鉴别材料 PDF】",
            "docPdf": f"../{doc_pdf.name}" if doc_pdf else "【待生成：说明书 PDF】",
        },
    }


def validate(form, d, spec):
    issues = []

    def add(level, field, msg, how):
        issues.append({"level": level, "field": field, "msg": msg, "how": how})

    flat = {k: v for sec in form.values() if isinstance(sec, dict) for k, v in sec.items()}
    for field, val in flat.items():
        if isinstance(val, str) and PLACEHOLDER.search(val):
            add("high", field, "未填写", PLACEHOLDER.search(val).group(0))
    for field, limit in LIMITS.items():
        val = flat.get(field, "")
        if isinstance(val, str) and not PLACEHOLDER.search(val) and chars(val) > limit:
            add("high", field, f"超长 {chars(val)}/{limit} 字", "精简后重跑")
    mf = flat.get("mainFunction", "")
    if not PLACEHOLDER.search(mf):
        n = chars(mf)
        if n < MAIN_MIN:
            add("high", "mainFunction", f"仅 {n} 字，不足 {MAIN_MIN} 字官网会拒绝",
                "先补完说明书功能模块章节的功能说明与操作步骤，再重跑本脚本")
        elif n > MAIN_MAX:
            add("high", "mainFunction", f"{n} 字，超过 {MAIN_MAX} 字", "删减次要模块")
    date = flat.get("completionDate", "")
    if not PLACEHOLDER.search(date) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        add("high", "completionDate", f"日期格式应为 YYYY-MM-DD，当前“{date}”", "改 ruanzhu.config.json")
    if flat.get("published") is not False:
        add("medium", "published", "发表状态不是“未发表”", "确认后再改；默认按未发表申报")
    for field in ("programPdf", "docPdf"):
        val = flat.get(field, "")
        if PLACEHOLDER.search(val):
            add("high", field, "PDF 未生成", "先跑 generate_source_docx.py / render_pdfs.py")
        elif not (d / "auto-fill" / val).resolve().exists():
            add("high", field, f"路径找不到文件：{val}", "确认材料目录结构")
    name = flat.get("softwareName", "")
    manual = d / "软件说明书.md"
    if manual.exists() and name not in manual.read_text(encoding="utf-8"):
        add("high", "softwareName", "说明书里找不到相同的软件全称", "各材料名称必须完全一致")
    if spec and flat.get("sourceLines", "").isdigit():
        if int(flat["sourceLines"]) != spec["stats"]["source_lines"]:
            add("medium", "sourceLines", "与素材统计不一致", "重跑 manual_spec.py 后再生成")
    return issues


def copy_md(form, issues, project):
    s2, s3, s4 = form["step2_basic"], form["step3_dev"], form["step4_features"]
    rows = [["软件全称", s2["softwareName"]], ["软件简称", s2["shortName"]], ["版本号", s2["version"]],
            ["软件分类", s2["category"]], ["著作权人", s2["copyrightHolder"]],
            ["开发完成日期", s2["completionDate"]], ["发表状态", "未发表" if s2["published"] is False else "已发表"],
            ["权利取得方式", form["step1_identity"]["acquireType"]], ["开发方式", form["step1_identity"]["developType"]],
            ["开发硬件环境", s3["devHardware"]], ["运行硬件环境", s3["runHardware"]],
            ["开发操作系统", s3["devOS"]], ["开发工具", s3["devTools"]],
            ["运行操作系统", s3["runOS"]], ["运行支撑环境", s3["runSupport"]],
            ["编程语言", s3["language"] + (f"（其他：{s3['languageOther']}）" if s3["languageOther"] else "")],
            ["源程序量", f"{s3['sourceLines']} 行（全项目源码行数）"],
            ["开发目的", s4["devPurpose"]], ["面向领域", s4["targetIndustry"]],
            ["技术特点标签", s4["techFeatureTag"]], ["技术特点", s4["techFeatureText"]]]
    out = [f"# {project['name']} {s2['version']} 申请表填报文案", "",
           "> 由 application_form.py 生成，与 `auto-fill/config.json` 同源；官网填报时对照本表复制。", "",
           "| 字段 | 填写内容 |", "| --- | --- |"]
    out += [f"| {k} | {v} |" for k, v in rows]
    out += ["", f"## 软件主要功能（{chars(s4['mainFunction'])} 字，官网要求 {MAIN_MIN}–{MAIN_MAX} 字）", "",
            s4["mainFunction"], "",
            "## 上传材料", "",
            f"- 程序鉴别材料：`{s4['programPdf']}`", f"- 文档鉴别材料：`{s4['docPdf']}`", ""]
    if issues:
        out += ["## 待处理", "", "| 级别 | 字段 | 问题 | 怎么办 |", "| --- | --- | --- | --- |"]
        out += [f"| {i['level']} | `{i['field']}` | {i['msg']} | {i['how']} |" for i in issues]
    else:
        out += ["## 校验", "", "全部字段通过校验，可运行 `node auto-fill/auto-fill.js` 自动填表并保存草稿。"]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="生成并校验申请表字段")
    ap.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    ap.add_argument("--spec", help="说明书素材.json（默认 <output_root>/说明书素材.json）")
    ap.add_argument("--project", help="只处理某一份（id）")
    ap.add_argument("--strict", action="store_true", help="存在高风险问题时退出码 1")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    spec = load(args.spec or root / "说明书素材.json")
    bad = 0
    for project in cfg["projects"]:
        if args.project and project["id"] != args.project:
            continue
        d = root / project["id"]
        (d / "auto-fill").mkdir(parents=True, exist_ok=True)
        form = build(cfg, project, root, spec, args)
        issues = validate(form, d, spec)
        (d / "auto-fill" / "config.json").write_text(json.dumps(form, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "申请表填报文案.md").write_text(copy_md(form, issues, project), encoding="utf-8")
        high = sum(1 for i in issues if i["level"] == "high")
        bad += high
        print(f"{project['name']}：主要功能 {chars(form['step4_features']['mainFunction'])} 字，"
              f"待处理 {len(issues)} 项（高 {high}）→ {d / 'auto-fill' / 'config.json'}")
        for i in issues[:8]:
            print(f"   [{i['level']}] {i['field']}：{i['msg']} —— {i['how']}")
    if args.strict and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
