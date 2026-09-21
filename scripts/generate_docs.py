#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_CHAPTERS = ["软件概述", "软件架构", "环境要求", "安装部署", "配置说明", "使用指南", "功能模块", "运维管理", "常见问题", "附录"]
# 保留旧名称，供外部脚本导入；新逻辑通过 chapter_names(project) 获取实际章节。
CHAPTERS = DEFAULT_CHAPTERS


def table(rows, headers):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)


def undent(text):
    """模板统一缩进 4 格；插入的多行表格没有缩进，textwrap.dedent 会失效，这里逐行去掉。"""
    return "\n".join(line[4:] if line.startswith("    ") else line for line in text.splitlines()) + "\n"


def load_spec(cfg, root, project):
    """说明书素材（manual_spec.py 产出）。项目可用 spec_modules 只取其中几个模块。"""
    path = Path(project.get("manual_spec") or cfg.get("manual_spec") or (root / "说明书素材.json"))
    if not path.exists():
        return None
    spec = json.loads(path.read_text(encoding="utf-8"))
    picked = project.get("spec_modules")
    if picked:
        spec["pages"] = [p for p in spec["pages"] if p["module"] in picked or p["file"] in picked]
    return spec


def load_shots(root, project):
    path = root / project["id"] / "截图清单.json"
    if not path.exists():
        return {}
    items = json.loads(path.read_text(encoding="utf-8")).get("items", [])
    by_module = {}
    for it in items:
        by_module.setdefault(it.get("module") or "", []).append(it)
    return by_module


def shot_md(module, shots, used):
    for it in shots.get(module, []):
        if it["file"] not in used:
            used.add(it["file"])
            return f"\n![{it['no']} {it['title']}]({it['file']})\n\n{it['no']}　{it['title']}\n"
    return f"\n【截图预留：{module}】\n"


def page_factual_intro(page):
    """素材没有人工 purpose 时，用源码抽到的入口/控件/约束拼出短事实段。

    不评价“优势/价值”，也不声称运行结果；事实不足时宁可少写。
    """
    parts = []
    entry = str(page.get("entry", "")).strip()
    name = str(page.get("module", "")).strip() or "该页面"
    elements = [str(x).strip() for x in page.get("elements", []) if str(x).strip()]
    validations = [str(x).strip() for x in page.get("validations", []) if str(x).strip()]
    feedbacks = [str(x).strip() for x in page.get("feedbacks", []) if str(x).strip()]
    if entry:
        parts.append(f"从 `{entry}` 进入“{name}”。")
    elif name:
        parts.append(f"源码中对应“{name}”页面。")
    if elements:
        parts.append(f"页面文字包括“{'”、“'.join(elements[:5])}”。")
    if validations:
        parts.append(f"源码记录的输入限制有：{'；'.join(validations[:3])}。")
    if feedbacks:
        parts.append(f"已抽取到的反馈文字包括“{'”、“'.join(feedbacks[:3])}”。")
    return "".join(parts) or "源码素材暂未抽取到足够的页面事实。"


def page_operation_steps(page):
    """从已抽取的源码事实生成最小操作骨架；不编造点击结果。"""
    name = str(page.get("module", "页面")).strip() or "页面"
    entry = str(page.get("entry", "")).strip()
    elements = [str(x).strip() for x in page.get("elements", []) if str(x).strip()]
    steps = []
    if entry:
        steps.append(f"从 `{entry}` 打开“{name}”。")
    else:
        steps.append(f"打开“{name}”页面。")
    if elements:
        steps.append(f"先核对页面中的“{elements[0]}”，再按页面提供的控件继续操作。")
    if len(elements) > 1:
        steps.append(f"根据需要查看“{'”、“'.join(elements[1:4])}”。")
    if page.get("validations"):
        steps.append("提交前按源码列出的输入限制检查字段值。")
    if page.get("feedbacks"):
        steps.append(f"完成后核对页面反馈：“{page['feedbacks'][0]}”。")
    return steps[:5]


def module_labels(page, index):
    """根据页面证据选择小节标题，避免每页复制同一组模板标题。"""
    has_validation = bool(page.get("validations"))
    has_feedback = bool(page.get("feedbacks"))
    first = ["入口与页面事实", "完成一次操作", "异常分支"]
    second = ["先看哪里", "按顺序操作", "结果与处理"]
    third = ["页面记录", "操作路径", "失败时检查"]
    labels = (first, second, third)[(index - 2) % 3]
    if not has_validation:
        labels[1] = "按顺序查看" if index % 2 == 0 else "操作路径"
    if not has_feedback:
        labels[2] = "未抽取到错误码" if not page.get("errors") else labels[2]
    return labels


def module_sections(project, spec=None, shots=None, used=None):
    """按“功能说明 / 界面与入口 / 操作步骤 / 异常处理”生成模块骨架——实测判人工的写法。
    有说明书素材时，界面元素、校验、提示语、错误码直接落到对应小节，Claude 只需补操作顺序。"""
    shots, used = shots or {}, used if used is not None else set()
    if not spec or not spec.get("pages"):
        out = []
        for i, (name, desc) in enumerate(modules(project), 2):
            out.append(
                f"## 7.{i} {name}\n\n"
                f"（一）功能说明\n\n{desc}【待改写：3-4 句，写输入、输出和不负责的范围】\n\n"
                "（二）操作步骤\n\n"
                "1. 【待填写：在“X”菜单进入 Y 界面】\n"
                "2. 【待填写：填写/选择的字段及取值约束】\n"
                "3. 【待填写：单击“X”后系统的反馈】\n\n"
                "（三）异常处理\n\n"
                "【待填写：失败时的提示文字或错误码，以及用户该怎么处理】\n"
                + shot_md(name, shots, used))
        return "\n".join(out)

    out = []
    for i, page in enumerate(spec["pages"], 2):
        name = page["module"]
        elements = "、".join(f"“{e}”" for e in page["elements"][:8]) or "【待填写：界面上的控件文字】"
        purpose = page.get("purpose") or page_factual_intro(page)
        scope = str(page.get("scope_note", "")).strip()
        steps = page.get("steps") or page_operation_steps(page)
        step_md = "\n".join(f"{n}. {st}" for n, st in enumerate(steps, 1))
        rows = [["进入位置", f"`{page['entry']}`"], ["界面元素", elements]]
        if page.get("validations"):
            rows.append(["取值约束", "；".join(page["validations"][:4])])
        if page.get("feedbacks"):
            rows.append(["操作反馈", "；".join(page["feedbacks"][:4])])
        err = table([[c, m, "按该提示检查输入、网络或当前页面状态。"] for c, m in page["errors"][:6]],
                    ["错误码/提示", "源码文字", "处理建议"]) if page.get("errors") else \
            ("页面素材未抽取到错误码；运行核验时记录实际返回。" if not page.get("feedbacks")
             else f"先核对页面反馈“{page['feedbacks'][0]}”，再按实际界面处理。")
        labels = module_labels(page, i)
        scope_line = f"\n\n范围说明：{scope}" if scope else ""
        out.append(
            f"## 7.{i} {name}\n\n"
            f"### {labels[0]}\n\n{purpose}{scope_line}\n\n"
            f"{table(rows, ['项目', '内容'])}\n\n"
            f"### {labels[1]}\n\n{step_md}\n\n"
            f"### {labels[2]}\n\n{err}\n"
            + shot_md(name, shots, used))
    return "\n".join(out)


def chapter_names(project):
    """默认使用十章，但复杂项目可通过 extra_chapters 增加项目专属章节。"""
    names = list(DEFAULT_CHAPTERS)
    seen = set(names)
    for item in project.get("extra_chapters", []) or []:
        title = item if isinstance(item, str) else item.get("title", "")
        title = re.sub(r"[\r\n#]", "", str(title)).strip()
        if title and title not in seen:
            names.append(title)
            seen.add(title)
    return names


def toc(chapters):
    return "# 目录\n\n" + "\n".join(f"- [{i + 1}. {name}](#{name})" for i, name in enumerate(chapters)) + "\n"


def extra_chapters(project, chapters):
    """渲染配置里的扩展章节；不要求项目启动，也不伪造运行数据。"""
    extras = project.get("extra_chapters", []) or []
    if not extras:
        return ""
    start = len(DEFAULT_CHAPTERS) + 1
    out = []
    for offset, item in enumerate(extras):
        if isinstance(item, str):
            title, intro, sections = item, "", []
        else:
            title = str(item.get("title", "扩展章节")).strip()
            intro = str(item.get("intro", "")).strip()
            sections = item.get("sections", []) or []
        number = start + offset
        out += [f"# {number} {title}", ""]
        if intro:
            out += [intro, ""]
        for sec_no, section in enumerate(sections, 1):
            if isinstance(section, str):
                sec_title, body = f"小节 {sec_no}", section
            else:
                sec_title = str(section.get("title", f"小节 {sec_no}")).strip()
                body = str(section.get("content", section.get("body", ""))).strip()
            out += [f"## {number}.{sec_no} {sec_title}", "", body or "【待补充：根据项目实际功能填写】", ""]
    return "\n".join(out)


def modules(project):
    return project.get("modules") or [["核心功能", "【待填写：模块入口文件与用户可见的操作】"]]


def source_map(project):
    return project.get("source_map") or [["核心源码", "【待补充】"]]


def users(project):
    return project.get("users") or ["【待核验：实际用户角色】"]


def numbered_steps(project, key, placeholder):
    steps = project.get(key) or [f"【待核验：{placeholder}】"]
    return "\n".join(f"{i}. {str(item)}" for i, item in enumerate(steps, 1))


def configured_rows(project, key, headers, placeholder):
    """只使用配置中的事实；缺失时输出待核验标记，不编造运行环境。"""
    rows = project.get(key)
    if isinstance(rows, list) and rows:
        normalized = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                normalized.append(list(row)[:len(headers)] + [""] * max(0, len(headers) - len(row)))
            elif isinstance(row, dict):
                normalized.append([row.get(h, "") for h in headers])
        if normalized:
            return normalized
    return [[placeholder] + [f"【待核验：{placeholder}】" for _ in headers[1:]]]


def configured_text(project, key, placeholder):
    value = project.get(key)
    if isinstance(value, str) and value.strip() and not value.strip().startswith("【待"):
        return value.strip()
    return f"【待核验：{placeholder}】"


def backend_project(project, spec=None):
    if project.get("document_kind") in {"backend", "api", "server"}:
        return True
    if spec and spec.get("backend"):
        return True
    files = " ".join(project.get("source_files", []) or []).lower()
    return any(x in files for x in ("/controller/", "/handler/", "/router/", "go.mod", "pom.xml", "manage.py"))


def evidence_plan(spec, project):
    if spec and spec.get("evidence_plan"):
        return spec["evidence_plan"]
    if backend_project(project, spec):
        return [
            {"id": "api-docs", "title": "Knife4j/OpenAPI 接口文档页", "required": False,
             "note": "仅在项目实际启用 Knife4j 或 OpenAPI 文档时截图；未确认时不虚构调试页"},
            {"id": "api-success", "title": "真实接口成功请求与 JSON 响应", "required": True,
             "note": "使用项目实际接口和业务字段，不使用测试占位词"},
            {"id": "api-error", "title": "参数校验失败或 HTTP 4xx 返回", "required": True,
             "note": "记录实际状态码和错误响应"},
            {"id": "runtime-log", "title": "启动日志与业务请求日志", "required": True,
             "note": "仅截项目真实输出，不补写日志内容"},
        ]
    return []


def manual(project, cfg, spec=None, shots=None):
    used = set()
    chapters = chapter_names(project)
    if spec and spec.get("pages"):
        module_table = table([[p["module"], f"`{p['entry']}`", f"`{p['file']}`"] for p in spec["pages"]],
                             ["模块", "进入位置", "源码文件"])
    else:
        module_table = table(modules(project), ["模块", "功能概述"])
    source_table = table(source_map(project), ["功能/层级", "源码位置"])
    user_table = table([[u, "【待核验：该角色在源码或界面中实际可执行的操作】"] for u in users(project)], ["角色", "实际操作范围"])
    name = project["name"]
    short = project.get("short_name", name)
    version = project.get("version", "V1.0")
    summary = project.get("summary", "【待核验：一句话说明软件用途和核心入口】")
    position = project.get("position", "【待核验：软件类型】")
    return undent(f"""\
    {toc(chapters)}

    # 软件概述

    ## 1.1 软件简介
    {name}（以下简称“{short}”）是一款{position}。{summary}

    ## 1.2 建设目标
    - 【待改写：写 2-4 个本软件要解决的具体问题，句式错开，每条挂一个源码事实】

    ## 1.3 软件范围
    {configured_text(project, "scope", "软件负责的业务范围和不负责的边界")}

    ## 1.4 核心特性
    {module_table}

    ## 1.5 适用范围
    {table(configured_rows(project, "scenarios", ["范围", "实际使用说明"], "实际使用范围"), ["范围", "实际使用说明"])}

    ## 1.6 主要用户角色
    {user_table}

    ## 1.7 源码范围
    - 文档版本：{version}（仅用于说明书内部核对，不代表申请表字段）
    - 相关源码：
    {source_table}

    # 软件架构

    ## 2.1 整体架构概览
    {configured_text(project, "architecture_overview", "源码中的实际架构和调用关系")}

    ## 2.2 分层架构
    {table(configured_rows(project, "architecture_layers", ["层级", "源码证据和职责"], "实际架构层级"), ["层级", "源码证据和职责"])}

    ## 2.3 关键模块架构
    {module_table}

    ## 2.4 数据流转流程
    {configured_text(project, "data_flow", "一次真实请求从入口到响应的流转步骤")}

    ## 2.5 技术选型
    {table(configured_rows(project, "tech_stack", ["类别", "技术组件", "用途"], "实际技术选型"), ["类别", "技术组件", "用途"])}

    # 环境要求

    ## 3.1 硬件环境
    {table(configured_rows(project, "hardware", ["硬件项", "最低配置", "推荐配置"], "实际硬件要求"), ["硬件项", "最低配置", "推荐配置"])}

    ## 3.2 软件环境
    {table(configured_rows(project, "environment", ["软件项", "说明"], "实际运行环境"), ["软件项", "说明"])}

    ## 3.3 权限要求
    {table(configured_rows(project, "permissions", ["权限", "源码或部署配置中的依据"], "实际权限要求"), ["权限", "源码或部署配置中的依据"])}

    # 安装部署

    ## 4.1 安装前准备
    {configured_text(project, "install_prerequisites", "项目实际安装前置条件")}

    ## 4.2 安装步骤
    {numbered_steps(project, "install_steps", "实际安装命令")}

    ## 4.3 部署后验证
    {table(configured_rows(project, "verification", ["验证项", "实际验证方式"], "实际部署验证"), ["验证项", "实际验证方式"])}

    # 配置说明

    ## 5.1 配置概述
    {configured_text(project, "configuration_overview", "项目实际配置项和生效方式")}

    ## 5.2 配置项清单
    {table(configured_rows(project, "config_items", ["配置项", "取值/来源", "实际作用"], "实际配置项"), ["配置项", "取值/来源", "实际作用"])}

    # 使用指南

    ## 6.1 快速上手
    {numbered_steps(project, "quick_start", "从真实入口开始的操作步骤")}

    ## 6.2 常用操作
    {table(configured_rows(project, "operations", ["操作", "实际步骤", "实际结果"], "实际操作记录"), ["操作", "实际步骤", "实际结果"])}

    # 功能模块

    ## 7.1 模块一览
    {module_table}

    {module_sections(project, spec, shots, used)}

    # 运维管理

    ## 8.1 日志与监控
    {configured_text(project, "logging", "实际日志文件、字段和查看方式")}

    ## 8.2 数据与缓存管理
    {configured_text(project, "data_maintenance", "实际数据、缓存和备份处理方式")}

    ## 8.3 安全策略
    {configured_text(project, "security", "源码和部署配置中实际存在的安全措施")}

    # 常见问题

    ## 9.1 常见问题
    {table(configured_rows(project, "faq", ["问题现象", "项目实际处理方法"], "实际问题和处理方式"), ["问题现象", "项目实际处理方法"])}

    # 附录

    ## 10.1 术语表
    {table(configured_rows(project, "terms", ["术语", "项目中的实际含义"], "实际术语"), ["术语", "项目中的实际含义"])}

    ## 10.2 测试用例
    {table(configured_rows(project, "tests", ["编号", "场景", "实际结果"], "实际测试记录"), ["编号", "场景", "实际结果"])}

    ## 10.3 截图清单
    {shot_table(project, shots, spec)}

    {extra_chapters(project, chapters)}
    """)


def shot_table(project, shots, spec=None):
    rows = [[it["no"], it["title"], f"`{it['file']}`"] for items in (shots or {}).values() for it in items]
    existing_ids = {it.get("evidence_id") for items in (shots or {}).values() for it in items}
    for item in evidence_plan(spec, project):
        if item.get("id") not in existing_ids:
            rows.append([f"待截图·{item.get('id')}", item.get("title", "待补充真实证据"), "【待截图】"])
    if not rows:
        rows = [["【待补充】", "运行 screenshots.py 整理真实截图后自动填充", "—"]]
    return table(sorted(rows), ["编号", "截图", "文件"])


def evidence_plan_markdown(project, spec=None):
    plan = evidence_plan(spec, project)
    if not plan:
        return "# 截图证据计划\n\n当前项目未识别为后端/API 项目，按项目实际情况补充截图。\n"
    lines = ["# 截图证据计划", "", "以下条目必须来自真实运行结果或项目实际调试页面，不得用占位图或虚构数据替代。", "", "| ID | 证据 | 必须 | 采集说明 |", "|---|---|---|---|"]
    for item in plan:
        required = "是" if item.get("required", True) else "否"
        lines.append(f"| {item.get('id', '')} | {item.get('title', '')} | {required} | {item.get('note', '')} |")
    return "\n".join(lines) + "\n"


def write_project(root, cfg, project, spec=None):
    out = root / project["id"]
    chapters = out / "说明书章节"
    source_dir = out / "源程序提取"
    chapters.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    shots = load_shots(root, project)
    text = manual(project, cfg, spec, shots)
    (out / "软件说明书.md").write_text(text, encoding="utf-8")
    (out / "申请表填报文案.md").write_text(application_copy(project, cfg, spec), encoding="utf-8")
    (out / "源码材料清单.md").write_text(source_list(project), encoding="utf-8")
    (out / "截图证据计划.md").write_text(evidence_plan_markdown(project, spec), encoding="utf-8")
    chapters_list = chapter_names(project)
    chapter_markers = [
        f"# {chapter}" if idx <= len(DEFAULT_CHAPTERS) else f"# {idx} {chapter}"
        for idx, chapter in enumerate(chapters_list, 1)
    ]
    for idx, chapter in enumerate(chapters_list, 1):
        marker = chapter_markers[idx - 1]
        start = text.find(marker)
        end = text.find(f"\n{chapter_markers[idx]}", start + 1) if idx < len(chapters_list) else len(text)
        if start >= 0:
            (chapters / f"{idx:02d}-{chapter}.md").write_text(text[start:end].strip() + "\n", encoding="utf-8")


def run_initial_aigc(root, projects):
    """对首次生成的文案做本地机械清理并生成任务单/报告。

    这里只调用离线脚本，不上传任何材料；事实性段落仍需按任务单人工确认。
    """
    script_dir = Path(__file__).resolve().parent
    for project in projects:
        material_dir = root / project["id"]
        rewrite = subprocess.run(
            [sys.executable, str(script_dir / "aigc_rewrite.py"), str(material_dir), "--apply"],
            check=False,
        )
        if rewrite.returncode != 0:
            raise RuntimeError(f"AIGC 初稿处理失败：{material_dir}")
        check = subprocess.run(
            [sys.executable, str(script_dir / "aigc_check.py"), str(material_dir),
             "--report", str(material_dir / "AIGC检测报告.md")],
            check=False,
        )
        if check.returncode != 0:
            raise RuntimeError(f"AIGC 初稿检查失败：{material_dir}")


def spec_lines(spec):
    if not spec:
        return "【待填写：项目全部源码行数，跑 `manual_spec.py` 可得；不是取材行数】"
    st = spec["stats"]
    return (f"{st['source_lines']} 行（{st['source_files']} 个源文件，manual_spec.py 统计）。"
            "申请表“源程序量”填全部源码行数，不是 60 页取材的行数。")


def application_copy(project, cfg, spec=None):
    return undent(f"""\
    # {project["name"]} {project.get("version", "V1.0")} 申请表填报文案

    | 项目 | 建议填写 |
    | --- | --- |
    | 软件全称 | {project["name"]} |
    | 软件简称 | {project.get("short_name", project["name"])} |
    | 版本号 | {project.get("version", "V1.0")} |
    | 软件分类 | 应用软件 |
    | 著作权人 | {cfg.get("copyright_holder", "【待填写】")} |
    | 开发完成日期 | {cfg.get("development_completed_date", "【待填写】")} |
    | 首次发表日期 | {cfg.get("first_publication_date", "未发表")} |
    | 权利取得方式 | 原始取得【待确认】 |
    | 开发方式 | 独立开发【待确认】 |

    ## 软件主要功能
    {project.get("summary", "【待改写：只写本软著的功能，500-1300 字，按操作动线描述】")}

    ## 源程序量
    {spec_lines(spec)}

    ## 开发工具
    【待填写：IDE / 编译器 / 构建工具等实际使用的工具，50 字内；不要写 React、Vue 这类技术栈名】

    ## 技术特点
    【待改写：100 字以内，写真实技术栈版本号与一个关键实现取舍，如“采用 A 而非 B，因为……”】
    """)


def source_list(project):
    files = project.get("source_files", [])
    rows = [[str(i + 1), f"`{f}`"] for i, f in enumerate(files)]
    return "# 源码材料清单\n\n" + table(rows, ["序号", "文件路径"]) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Generate soft-copyright docs from ruanzhu.config.json; runtime startup is not required.")
    parser.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    parser.add_argument("--skip-aigc", action="store_true",
                        help="跳过首次生成后的本地 AIGC 机械清理；默认自动执行，不联网")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    root.mkdir(parents=True, exist_ok=True)
    for project in cfg["projects"]:
        write_project(root, cfg, project, load_spec(cfg, root, project))
    if not args.skip_aigc:
        run_initial_aigc(root, cfg["projects"])
    (root / "待补充信息清单.md").write_text(
        "# 待补充信息清单\n\n- 著作权人\n- 开发完成日期\n- 发表状态（默认未发表）\n- 权利取得方式\n- 开发方式\n- 联系人和联系方式\n",
        encoding="utf-8",
    )
    print(root)


if __name__ == "__main__":
    main()
