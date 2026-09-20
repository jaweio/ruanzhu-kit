#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


CHAPTERS = ["软件概述", "软件架构", "环境要求", "安装部署", "配置说明", "使用指南", "功能模块", "运维管理", "常见问题", "附录"]


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
        purpose = page.get("purpose") or "【待改写：3-4 句，写这个界面解决什么、输入输出是什么】"
        scope = page.get("scope_note") or "【待填写：本功能不负责的范围，如“不修改原始数据”】"
        steps = page.get("steps") or [
            f"【待填写：进入 `{page['entry']}`】",
            f"【待填写：在界面中选择或填写，可用控件：{'、'.join(page['elements'][:4]) or '待补'}】",
            "【待填写：单击确认后系统的反馈】",
        ]
        step_md = "\n".join(f"{n}. {st}" for n, st in enumerate(steps, 1))
        rows = [["进入位置", f"`{page['entry']}`"], ["界面元素", elements]]
        if page.get("validations"):
            rows.append(["取值约束", "；".join(page["validations"][:4])])
        if page.get("feedbacks"):
            rows.append(["操作反馈", "；".join(page["feedbacks"][:4])])
        err = table([[c, m, "【待填写：用户该怎么处理】"] for c, m in page["errors"][:6]],
                    ["错误码/提示", "含义", "处理方法"]) if page.get("errors") else \
            "【待填写：失败时的提示文字或错误码，以及用户该怎么处理】"
        out.append(
            f"## 7.{i} {name}\n\n"
            f"（一）功能说明\n\n{purpose}{scope}\n\n"
            f"（二）界面与入口\n\n{table(rows, ['项目', '内容'])}\n\n"
            f"（三）操作步骤\n\n{step_md}\n\n"
            f"（四）异常处理\n\n{err}\n"
            + shot_md(name, shots, used))
    return "\n".join(out)


def toc():
    return "# 目录\n\n" + "\n".join(f"- [{i + 1}. {name}](#{name})" for i, name in enumerate(CHAPTERS)) + "\n"


def modules(project):
    return project.get("modules") or [["核心功能", "【待填写：模块入口文件与用户可见的操作】"]]


def source_map(project):
    return project.get("source_map") or [["核心源码", "【待补充】"]]


def users(project):
    return project.get("users") or ["普通用户", "管理员", "运维人员"]


def manual(project, cfg, spec=None, shots=None):
    used = set()
    if spec and spec.get("pages"):
        module_table = table([[p["module"], f"`{p['entry']}`", f"`{p['file']}`"] for p in spec["pages"]],
                             ["模块", "进入位置", "源码文件"])
    else:
        module_table = table(modules(project), ["模块", "功能概述"])
    source_table = table(source_map(project), ["功能/层级", "源码位置"])
    user_table = table([[u, "使用或管理本软件相关功能。"] for u in users(project)], ["角色", "需求与价值"])
    name = project["name"]
    short = project.get("short_name", name)
    version = project.get("version", "V1.0")
    summary = project.get("summary", "【待改写：一句话说明用户用它做什么，引用入口文件或核心模块路径】")
    position = project.get("position", "应用软件")
    return undent(f"""\
    {toc()}

    # 软件概述

    ## 1.1 软件简介
    {name}（以下简称“{short}”）是一款{position}。{summary}

    ## 1.2 建设目标
    - 【待改写：写 2-4 个本软件要解决的具体问题，句式错开，每条挂一个源码事实】

    ## 1.3 设计原则
    {table([["易用性", "提供清晰的界面和操作流程。"], ["模块化", "按功能边界拆分模块，便于维护。"], ["可扩展性", "支持后续新增功能和外部集成。"], ["安全性", "对关键数据、权限和操作进行约束。"], ["可追溯", "保留必要日志、记录和诊断信息。"]], ["原则", "说明"])}

    ## 1.4 核心特性
    {module_table}

    ## 1.5 适用场景
    - 日常业务处理和任务管理。
    - 项目内数据、文件、配置或流程管理。
    - 企业或团队内部工具化应用。
    - 软件运行维护和问题诊断。

    ## 1.6 主要用户角色
    {user_table}

    ## 1.7 版本信息
    - 当前版本：{version}
    - 著作权人：{cfg.get("copyright_holder", "【待填写】")}
    - 开发完成日期：{cfg.get("development_completed_date", "【待填写】")}
    - 首次发表日期：{cfg.get("first_publication_date", "未发表")}
    - 相关源码：
    {source_table}

    # 软件架构

    ## 2.1 整体架构概览
    本软件采用分层架构设计，通常包括用户交互层、业务服务层、数据访问层和基础设施层。用户通过界面或接口发起操作，业务服务层完成流程调度，数据访问层负责本地或远端数据读写，基础设施层提供日志、配置、安全和部署支撑。

    ## 2.2 分层架构
    {table([["表现层", "负责页面展示、输入交互、状态反馈。"], ["业务层", "负责业务规则、流程编排和模块协同。"], ["服务层", "封装配置、日志、文件、网络、任务等通用能力。"], ["数据层", "保存业务数据、配置数据、日志数据和运行状态。"]], ["层级", "说明"])}

    ## 2.3 关键模块架构
    {module_table}

    ## 2.4 数据流转流程
    ```
    用户操作 → 参数校验 → 业务服务处理 → 数据读写或外部调用
      → 返回处理结果 → 界面展示 → 日志记录
    ```

    ## 2.5 技术选型
    {table([["开发语言", "按项目实际填写", "实现业务逻辑。"], ["运行平台", "Windows/macOS/Linux/Web/移动端", "根据项目实际支持平台填写。"], ["数据存储", "本地数据库/远端数据库/文件", "保存配置和业务数据。"], ["构建工具", "按项目实际填写", "完成编译、构建和发布。"]], ["类别", "技术组件", "用途"])}

    # 环境要求

    ## 3.1 硬件环境
    {table([["CPU", "双核及以上", "四核及以上"], ["内存", "4GB", "8GB 及以上"], ["存储", "500MB 可用空间", "2GB 及以上"], ["网络", "按需", "稳定网络连接"]], ["硬件项", "最低配置", "推荐配置"])}

    ## 3.2 软件环境
    {table([["操作系统", "按项目实际支持平台填写"], ["运行时", "按项目实际依赖填写"], ["数据库", "按项目实际依赖填写"], ["浏览器/客户端", "按项目实际填写"]], ["软件项", "说明"])}

    ## 3.3 权限要求
    {table([["文件访问", "读取或写入项目相关文件。"], ["网络访问", "访问接口、模型服务或远端资源。"], ["日志访问", "查看运行日志和诊断信息。"]], ["权限", "作用"])}

    # 安装部署

    ## 4.1 安装前准备
    - 确认操作系统和运行环境满足要求。
    - 准备安装包、源码或部署文件。
    - 准备必要账号、密钥、数据库或接口地址。

    ## 4.2 安装步骤
    1. 获取软件安装包或源码。
    2. 安装依赖或运行环境。
    3. 执行构建或安装命令。
    4. 启动软件并完成初始化配置。

    ## 4.3 部署后验证
    {table([["启动验证", "软件可正常启动。"], ["配置验证", "关键配置可保存并生效。"], ["功能验证", "核心功能流程可完成。"], ["日志验证", "运行日志可查看。"]], ["验证项", "验证内容"])}

    # 配置说明

    ## 5.1 配置概述
    软件配置包括基础参数、业务参数、运行参数、安全参数和扩展参数。配置应根据实际部署环境填写，并在变更后进行验证。

    ## 5.2 配置项清单
    {table(project.get("config_items", [["基础配置", "按项目实际填写", "控制软件基础运行行为。"], ["业务配置", "按项目实际填写", "控制业务流程和功能开关。"]]), ["配置项", "取值/来源", "说明"])}

    # 使用指南

    ## 6.1 快速上手
    1. 启动软件。
    2. 完成基础配置。
    3. 进入核心功能页面。
    4. 按业务流程录入或选择数据。
    5. 查看处理结果并保存。

    ## 6.2 常用操作
    {table(project.get("operations", [["创建任务", "输入任务信息并保存。", "任务创建成功。"], ["查看结果", "打开结果页面或列表。", "结果正常展示。"]]), ["操作", "步骤", "结果"])}

    # 功能模块

    ## 7.1 模块一览
    {module_table}

    {module_sections(project, spec, shots, used)}

    # 运维管理

    ## 8.1 日志与监控
    软件应记录启动、配置、核心操作、异常和关键状态变更日志，便于运维人员定位问题。

    ## 8.2 数据与缓存管理
    定期检查数据文件、缓存目录、日志目录和临时文件，避免长期运行导致磁盘空间不足。

    ## 8.3 安全策略
    对敏感配置、账号密钥、用户数据和关键操作进行权限控制、脱敏处理和日志审计。

    # 常见问题

    ## 9.1 软件无法启动怎么办？
    检查运行环境、依赖安装、配置文件和日志输出。

    ## 9.2 配置不生效怎么办？
    检查配置保存路径、字段名称、运行环境和重启要求。

    ## 9.3 功能执行失败怎么办？
    查看错误提示和日志，确认输入数据、权限、网络和依赖是否正常。

    # 附录

    ## 10.1 术语表
    {table(project.get("terms", [["软件著作权", "计算机软件作品权利登记相关事项。"], ["源程序鉴别材料", "用于证明软件源代码内容的材料。"]]), ["术语", "说明"])}

    ## 10.2 测试用例
    {table(project.get("tests", [["TC-001", "启动软件", "软件正常打开。"], ["TC-002", "核心功能", "核心流程执行成功。"], ["TC-003", "异常提示", "异常情况下给出明确提示。"]]), ["编号", "场景", "预期结果"])}

    ## 10.3 截图清单
    {shot_table(project, shots)}
    """)


def shot_table(project, shots):
    rows = [[it["no"], it["title"], f"`{it['file']}`"] for items in (shots or {}).values() for it in items]
    if not rows:
        rows = [["【待补充】", "运行 screenshots.py 整理截图后自动填充", "—"]]
    return table(sorted(rows), ["编号", "截图", "文件"])


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
    for idx, chapter in enumerate(CHAPTERS, 1):
        marker = f"# {chapter}"
        start = text.find(marker)
        end = text.find(f"\n# {CHAPTERS[idx]}", start + 1) if idx < len(CHAPTERS) else len(text)
        if start >= 0:
            (chapters / f"{idx:02d}-{chapter}.md").write_text(text[start:end].strip() + "\n", encoding="utf-8")


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
    parser = argparse.ArgumentParser(description="Generate soft-copyright docs from ruanzhu.config.json.")
    parser.add_argument("--config", default="soft-copyright-materials/ruanzhu.config.json")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(cfg.get("output_root", "soft-copyright-materials"))
    root.mkdir(parents=True, exist_ok=True)
    for project in cfg["projects"]:
        write_project(root, cfg, project, load_spec(cfg, root, project))
    (root / "待补充信息清单.md").write_text(
        "# 待补充信息清单\n\n- 著作权人\n- 开发完成日期\n- 发表状态（默认未发表）\n- 权利取得方式\n- 开发方式\n- 联系人和联系方式\n",
        encoding="utf-8",
    )
    print(root)


if __name__ == "__main__":
    main()

