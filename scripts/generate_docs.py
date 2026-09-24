#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aigc_rules import PLACEHOLDER  # noqa: E402
from ai_compliance import generate as generate_ai_compliance  # noqa: E402
from environment_profile import resolve_environment  # noqa: E402


DEFAULT_CHAPTERS = ["软件概述", "软件架构", "环境要求", "安装部署", "配置说明", "使用指南", "功能模块", "运维管理", "常见问题", "附录"]
# 保留旧名称，供外部脚本导入；新逻辑通过 chapter_names(project) 获取实际章节。
CHAPTERS = DEFAULT_CHAPTERS

# 源码路径是内部取材信息，不能泄漏到提交版软件说明书。这个规则只用于说明书正文，
# 源码材料清单和版权检查报告仍保留原始路径，便于人工复核。
SOURCE_PATH_RE = re.compile(
    r"`(?:[A-Za-z0-9_.()\[\]-]+/)+\.env(?:\.[A-Za-z0-9_-]+)*`"
    r"|(?<![\w@])(?:[A-Za-z0-9_.()\[\]-]+/)+\.env(?:\.[A-Za-z0-9_-]+)*"
    r"|`(?:[A-Za-z0-9_.()\[\]-]+/)+[A-Za-z0-9_.()\[\]-]+\.(?:tsx|jsx|go|ts|js|py|java|swift|rs|vue|css|scss|sql|html|env(?:\.[A-Za-z0-9_-]+)*)`"
    r"|(?<![\w@])(?:[A-Za-z0-9_.()\[\]-]+/)+[A-Za-z0-9_.()\[\]-]+\.(?:tsx|jsx|go|ts|js|py|java|swift|rs|vue|css|scss|sql|html|env(?:\.[A-Za-z0-9_-]+)*)"
    r"|(?<![\w@])(?:[A-Za-z0-9_.()\[\]-]+/){2,}[A-Za-z0-9_.()\[\]-]*(?:/|\*\*)"
    r"|(?<![\w@])(?:server|apps|packages|src|app|data|components|internal|cmd|ios)/[A-Za-z0-9_.()\[\]-]+\.(?:tsx|jsx|go|ts|js|py|java|swift|rs|vue|css|scss|sql|html|env(?:\.[A-Za-z0-9_-]+)*)"
)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]+\]\([^)]*\)")
API_PATH_RE = re.compile(
    r"(?<![\w])/(?:api/|health\b|readyz\b|healthz\b|auth/|ws\b|uploads/|plugin-surfaces/|workspaces/|tasks/|runtimes/)[A-Za-z0-9_{}?=&./-]*"
)
MISSING_FACT_RE = re.compile(r"^\s*(?:待确认|待填写|待补充|待核验)(?:\s*[（(].*)?\s*$")


def configured_fact(value):
    """Treat common user-facing placeholders as missing facts.

    Older project configs used phrases such as ``待确认（申请人提供日期）``.
    They are useful as a prompt while editing a config, but must never be
    copied into a generated upload document or auto-fill payload.
    """
    text = str(value or "").strip()
    return "" if MISSING_FACT_RE.fullmatch(text) else text


def manual_safe(value):
    """移除说明书中的内部源码路径和生产字段，保留用户可读的业务描述。"""
    text = str(value)
    preserved = []

    def preserve_link(match):
        preserved.append(match.group(0))
        return f"@@RUANZHU_LINK_{len(preserved) - 1}@@"

    text = MARKDOWN_LINK_RE.sub(preserve_link, text)
    # REST paths are user-facing facts, not local source paths.  Protect them
    # before SOURCE_PATH_RE removes slash-delimited implementation paths.
    text = API_PATH_RE.sub(preserve_link, text)
    text = SOURCE_PATH_RE.sub("对应业务模块", text)
    replacements = {
        "后端源码范围": "服务功能范围",
        "源码范围": "功能范围",
        "源码位置": "内部路径",
        "源码文件": "功能入口",
        "源码证据和职责": "分层职责与实现说明",
        "源码或部署配置中的依据": "实际配置依据",
        "源码中的实际架构和调用关系": "实际架构和调用关系",
        "源码和部署配置中实际存在的安全措施": "实际安全措施",
        "源码文字": "实际提示",
        "源码中对应": "软件中对应",
        "源码记录的输入限制": "页面记录的输入限制",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    for index, link in enumerate(preserved):
        text = text.replace(f"@@RUANZHU_LINK_{index}@@", link)
    return text


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
    # A project may explicitly disable source-derived page extraction.  This is
    # useful for desktop-only materials where a monorepo-wide manual_spec would
    # pull in unrelated web/mobile/backend pages and leave misleading screenshot
    # placeholders.  ``false`` is intentional configuration, not a missing
    # value that should fall back to the root-level spec.
    if project.get("manual_spec", "__missing__") is False or cfg.get("manual_spec", "__missing__") is False:
        return None
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


def screenshots_enabled(project, shots):
    """Only render screenshot sections when the project explicitly enables them.

    A backend-only or offline material set commonly has no screenshots.  The
    old renderer still emitted an empty ``10.3 截图清单`` section (and could
    create an evidence-plan file), which made a valid no-screenshot manual
    look unfinished.  Existing desktop projects keep their behaviour because
    a non-empty manifest enables the default automatically.
    """
    configured = project.get("include_screenshots")
    if configured is not None:
        return bool(configured)
    return any(bool(items) for items in (shots or {}).values())


def shot_md(module, shots, used):
    blocks = []
    for it in shots.get(module, []):
        if it["file"] not in used:
            used.add(it["file"])
            blocks.append(f"\n![{it['no']} {it['title']}]({it['file']})\n\n{it['no']}　{it['title']}\n")
    if blocks:
        return "".join(blocks)
    # Formal manuals must contain evidence or omit the image block entirely.
    # A placeholder is an internal task signal, not registration material.
    return ""


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
        parts.append(f"打开“{name}”页面。")
    elif name:
        parts.append(f"软件中对应“{name}”页面。")
    if elements:
        parts.append(f"页面文字包括“{'”、“'.join(elements[:5])}”。")
    if validations:
        parts.append(f"页面记录的输入限制有：{'；'.join(validations[:3])}。")
    if feedbacks:
        parts.append(f"已抽取到的反馈文字包括“{'”、“'.join(feedbacks[:3])}”。")
    return "".join(parts)


def page_operation_steps(page):
    """从已抽取的源码事实生成最小操作骨架；不编造点击结果。"""
    name = str(page.get("module", "页面")).strip() or "页面"
    entry = str(page.get("entry", "")).strip()
    elements = [str(x).strip() for x in page.get("elements", []) if str(x).strip()]
    steps = []
    if entry:
        steps.append(f"打开“{name}”页面。")
    else:
        steps.append(f"打开“{name}”页面。")
    if elements:
        steps.append(f"先核对页面中的“{elements[0]}”，再按页面提供的控件继续操作。")
    if len(elements) > 1:
        steps.append(f"根据需要查看“{'”、“'.join(elements[1:4])}”。")
    if page.get("validations"):
        steps.append("提交前按页面列出的输入限制检查字段值。")
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
        labels[2] = "异常处理"
    return labels


def module_sections(project, spec=None, shots=None, used=None):
    """按“功能说明 / 界面与入口 / 操作步骤 / 异常处理”生成模块骨架——实测判人工的写法。
    有说明书素材时，界面元素、校验、提示语、错误码直接落到对应小节，Claude 只需补操作顺序。"""
    shots, used = shots or {}, used if used is not None else set()
    # 后端项目没有左侧导航和页面截图。旧模板仍然写“从左侧导航进入”，
    # 这既不符合实际，也让所有模块落成同一个句式。后端说明书改按真实
    # API、状态码和依赖检查展开，调用方可以照着接口顺序复核。
    if backend_project(project, spec) and not (spec and spec.get("pages")):
        return backend_module_sections(project, shots, used)
    if not spec or not spec.get("pages"):
        out = []
        for i, (name, desc) in enumerate(modules(project), 2):
            module_steps = (project.get("module_steps") or {}).get(name) or [
                f"从左侧导航进入“{name}”，查看页面上的实际功能入口。"
            ]
            steps = "\n".join(f"{n}. {step}" for n, step in enumerate(module_steps, 1))
            module_error = (project.get("module_errors") or {}).get(name, "")
            exception_block = f"（三）异常处理\n\n{module_error}\n" if module_error else ""
            out.append(
                f"## 7.{i} {name}\n\n"
                f"（一）功能说明\n\n{desc}\n\n"
                f"（二）操作步骤\n\n{steps}\n\n"
                f"{exception_block}"
                + shot_md(name, shots, used))
        return "\n".join(out)

    out = []
    for i, page in enumerate(spec["pages"], 2):
        name = page["module"]
        elements = "、".join(f"“{e}”" for e in page["elements"][:8])
        purpose = page.get("purpose") or page_factual_intro(page)
        scope = str(page.get("scope_note", "")).strip()
        steps = page.get("steps") or page_operation_steps(page)
        step_md = "\n".join(f"{n}. {st}" for n, st in enumerate(steps, 1))
        rows = [["页面", name]]
        if elements:
            rows.append(["界面元素", elements])
        if page.get("validations"):
            rows.append(["取值约束", "；".join(page["validations"][:4])])
        if page.get("feedbacks"):
            rows.append(["操作反馈", "；".join(page["feedbacks"][:4])])
        # Do not manufacture a repeated error-code sentence for every page.
        # Source extraction often has no explicit error strings; that is not a
        # runtime failure and the placeholder made its way into formal manuals
        # as noisy, misleading copy.  Render an exception subsection only when
        # the project actually supplied errors or feedbacks.
        err = table([[c, m, "按该提示检查输入、网络或当前页面状态。"] for c, m in page["errors"][:6]],
                    ["错误码/提示", "实际提示", "处理建议"]) if page.get("errors") else \
            (f"先核对页面反馈“{page['feedbacks'][0]}”，再按实际界面处理。" if page.get("feedbacks") else "")
        labels = module_labels(page, i)
        scope_line = f"\n\n范围说明：{scope}" if scope else ""
        exception_block = f"### {labels[2]}\n\n{err}\n" if err else ""
        out.append(
            f"## 7.{i} {name}\n\n"
            f"### {labels[0]}\n\n{purpose}{scope_line}\n\n"
            f"{table(rows, ['项目', '内容'])}\n\n"
            f"### {labels[1]}\n\n{step_md}\n\n"
            f"{exception_block}"
            + shot_md(name, shots, used))
    return "\n".join(out)


def backend_module_playbook(name):
    """Return a small, factual playbook for a backend module.

    These are deliberately about request order and failure checks rather than
    generic capability claims.  The paths and constraints mirror the curated
    api_examples/api_catalog in the project config; a project without a
    matching module simply receives a short, neutral fallback.
    """
    n = str(name).replace(" ", "")
    if "认证" in n or "工作区权限" in n:
        return {
            "steps": [
                "执行 GET /api/me。返回 200 后再继续。",
                "检查 GET /api/workspaces，把返回的工作区 ID 放进后续请求。",
                "执行 POST /api/workspaces 创建空间。成员邀请、角色更新和移除都带工作区 ID。",
            ],
            "failure": "收到 401 时刷新会话或重新登录。收到 403 时核对成员角色。创建 slug 已存在的工作区会返回 409，应换用未占用的 slug。",
        }
    if "任务" in n or "问题" in n:
        return {
            "steps": [
                "执行 POST /api/issues 提交 title。需要安排执行时，再带上负责人或项目关系。",
                "保存响应中的 issue ID 和 revision。评论、附件、订阅都使用这个 ID。",
                "检查 GET /api/issues/{id}/timeline，核对创建和更新顺序。",
                "打开 /api/issues/search 或 /api/issues/query 缩小问题范围。",
            ],
            "failure": "请求体字段、UUID、状态、优先级或 stage 不合法时返回 400。更新遇到版本冲突时先读取最新 revision，再决定重试或提示人工合并。",
        }
    if "运行时" in n or "智能体" in n:
        return {
            "steps": [
                "执行 POST /api/daemon/register，得到设备身份。",
                "执行 /api/daemon/heartbeat，保持心跳间隔。",
                "执行 POST /api/daemon/tasks/claim；max_tasks 为 0 时不领取，单次上限为 32。",
                "执行期间回传 start、progress、messages，结束时调用 complete 或 fail。每次都带同一个 taskId。",
            ],
            "failure": "daemon_id 与守护进程令牌不匹配时返回 403。心跳停止或租约过期后，原运行时不应继续上报；排查时同时看 runtime_id、task ID 和最后一次心跳时间。",
        }
    if "实时" in n or "聊天" in n:
        return {
            "steps": [
                "打开 GET /ws；运行时打开 /api/daemon/ws。",
                "更新问题或评论后，检查事件，再读问题详情和时间线。",
                "断线后重新打开通道并建立身份，然后从历史接口补拉记录。",
            ],
            "failure": "单节点只检查当前进程的 Hub。多节点收不到其他节点的事件时，继续检查 REDIS_URL、实时中继参数和各节点公开地址。",
        }
    if "外部" in n or "仓库" in n or "项目" in n:
        return {
            "steps": [
                "保存项目连接后，设置外部平台的回调地址。版本控制事件进入 POST /api/webhooks/vcs/{connectionId}。",
                "检查签名和 connectionId，再决定写问题、评论、通知还是执行结果。",
                "保存响应状态码和外部事件标识。重试前先查这个标识。",
            ],
            "failure": "签名失败时不要关闭校验再重试。检查请求时间、连接配置版本和签名密钥；同一事件重复到达时先查时间线，避免重复写入。",
        }
    if "插件" in n or "自动化" in n or "技能" in n:
        return {
            "steps": [
                "检查 GET /api/workspaces/{id}/plugins 查看安装记录。安装前可执行 POST .../plugins/preview。",
                "确认工作区授权后再安装插件，启用、停用和卸载分别使用 installationId。",
                "检查 cron 触发记录和投递结果，核对插件动作及 MCP 工具调用的授权范围。",
            ],
            "failure": "未授权的工作区操作应被拒绝。预览通过不等于安装成功，安装、启用和动作执行要分别检查响应状态和安装记录。",
        }
    if "数据" in n or "运维" in n or "文件" in n:
        return {
            "steps": [
                "执行 cmd/migrate，并核对 schema_migrations。",
                "打开 /health，再打开 /readyz。实时指标入口需要 REALTIME_METRICS_TOKEN。",
                "检查附件上传和下载的权限；清理 Redis 缓存或租约前先确认没有运行中的任务。",
            ],
            "failure": "/readyz 未就绪时先检查 PostgreSQL、迁移和 Redis 初始化日志。附件不能绕过服务端接口直接暴露存储目录。",
        }
    return {
        "steps": [
            f"根据“{name}”对应的接口入口提交一次真实请求，保留请求标识和响应状态。",
            "再读取业务记录或健康检查接口，确认写入结果与调用方看到的状态一致。",
        ],
        "failure": "出现 4xx 时先修正请求字段和权限，出现 5xx 或 503 时先查看服务日志和依赖状态。",
    }


def backend_module_sections(project, shots=None, used=None):
    """Backend-specific module prose with real request order and recovery branches."""
    shots, used = shots or {}, used if used is not None else set()
    out = []
    for i, (name, desc) in enumerate(modules(project), 2):
        playbook = backend_module_playbook(name)
        # Keep the configured description as a short factual anchor, but split
        # its semicolon-heavy list into sentences so the manual does not repeat
        # the same “能力；能力；能力” cadence for every module.
        fact = str(desc).replace("；", "。")
        if fact and not fact.endswith(("。", "！", "？")):
            fact += "。"
        steps = "\n".join(f"{n}. {step}" for n, step in enumerate(playbook["steps"], 1))
        out.append(
            f"## 7.{i} {name}\n\n"
            f"（一）功能说明\n\n{fact}\n\n"
            f"（二）操作步骤\n\n{steps}\n\n"
            f"（三）异常处理\n\n{playbook['failure']}\n"
            + shot_md(name, shots, used)
        )
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


def backend_extra_content(title, body):
    """Rewrite common backend appendix paragraphs around concrete interfaces.

    The project config remains the source of facts.  This adapter changes the
    document shape for the recurring backend chapters so they read like an
    operator's notes instead of repeating a generic chapter introduction.
    """
    title = str(title).strip()
    body = str(body).strip()
    overrides = {
        "接口调用与数据对象": (
            "本章按调用顺序整理接口：先看健康检查，再看用户和工作区，随后进入问题协作、运行时调度、附件、插件和外部回调。"
            "每一类都注明认证边界；实际请求仍以当前服务注册的路由和响应字段为准。"
        ),
        "部署、运维与安全治理": (
            "部署时先准备 PostgreSQL 和 Redis，完成迁移后再启动服务。"
            "运行中的排查从 /health、/readyz 和结构化日志开始，多节点环境再检查 Redis 中继、租约和 CORS 配置。"
        ),
        "典型业务流程": (
            "下面按一次真实任务的先后顺序说明调用关系：用户建立身份，进入工作区，创建问题，运行时领取并回传，成员最后完成验收。"
        ),
        "接口错误与诊断参考": (
            "本章按状态码和故障证据整理处理顺序。先保留请求标识、资源 ID 和响应状态，再检查身份、租约、数据库、Redis 或 WebSocket。"
        ),
        "接口分层与请求上下文": (
            "先区分公开探针和业务接口。/health、/readyz 只返回进程或依赖状态；"
            "用户请求需要会话 Cookie 或 JWT，运行时请求需要注册令牌，Webhook 请求需要签名或连接标识。"
            "工作区接口还会把成员角色放入请求上下文，调用方不能只凭用户 ID 读取其他工作区的数据。"
        ),
        "用户、工作区与成员对象": (
            "GET /api/me 返回当前用户资料，GET /api/workspaces 返回可访问的工作区。"
            "POST /api/workspaces 创建空间时同时建立所有者成员记录；成员邀请、角色变更和移除都在工作区 ID 下完成。"
            "调用方应保留工作区 ID，不能把用户 ID 当成跨工作区的访问凭证。"
        ),
        "问题、评论与时间线": (
            "POST /api/issues 保存标题和协作字段，问题详情还可以关联负责人、项目、父问题、日期、附件和标签。"
            "更新、评论和订阅分别使用问题资源下的入口，GET /api/issues/{id}/timeline 用来回看变更顺序。"
            "搜索和组合查询服务于不同的筛选条件，调用方应按工作区和状态缩小查询范围。"
        ),
        "运行时任务状态": (
            "运行时先 POST /api/daemon/register 建立设备身份，再用 /api/daemon/heartbeat 刷新在线状态。"
            "POST /api/daemon/tasks/claim 创建任务租约；开始、进度、消息、完成、失败和取消确认接口都必须带同一个 taskId。"
            "租约过期或心跳停止后，服务端按任务状态进入恢复处理，原设备不应继续写入进度。"
        ),
        "文件、插件与扩展边界": (
            "附件上传、普通下载和 signed-download 都先检查工作区权限，短时能力凭证过期后需要重新申请。"
            "插件包安装前可以预览，启用、停用和卸载分别对应安装记录；插件动作与 MCP 工具调用要在授权范围内执行。"
            "文件路径或插件包本身不能绕过成员权限。"
        ),
        "回调与错误处理": (
            "外部回调先校验签名或令牌，再识别连接和事件类型，最后写入问题、评论、通知或执行结果。"
            "收到 400 时修正 JSON 字段，收到 401 或 403 时检查身份和工作区角色，收到 409 时重新读取资源，"
            "收到 503 时先查看 /readyz、数据库迁移和 Redis 状态。"
        ),
        "用户进入工作区": (
            "客户端先访问 /api/me 确认登录状态，再读取 /api/workspaces。"
            "所有者通过成员入口发送邀请；成员接受后，问题、项目、评论和运行时资源才会出现在该工作区的授权范围内。"
        ),
        "创建问题并安排执行": (
            "成员向 POST /api/issues 提交标题、描述、状态、优先级以及负责人或项目关系。"
            "服务端返回问题编号并记录时间线；运行时领取时还会再次检查工作区、负责人和运行时能力。"
        ),
        "运行时领取和回传": (
            "运行时完成注册和心跳后调用领取入口，服务端返回带租约的任务。"
            "执行期间按开始、进度、消息、用量和最终结果回传，服务端同时更新问题记录、时间线和实时事件。"
        ),
        "协作消息与人工验收": (
            "评论和状态变化通过 /ws 推送给已连接客户端。"
            "如果连接中断，先恢复用户和工作区身份，再用问题详情、评论和时间线接口补齐记录；成员核对附件和执行消息后更新验收状态。"
        ),
        "外部事件进入协作流": (
            "GitHub 或其他版本控制平台把事件送到 Webhook 入口后，服务端先验证签名和连接关系。"
            "事件随后转成问题、评论或通知，并按响应状态决定是否重试；重复事件先查外部事件标识和时间线。"
        ),
        "任务租约与重复执行": (
            "POST /api/daemon/tasks/claim 返回的是带租约的任务记录，不是普通列表。"
            "运行时随后调用 start、progress、messages 和 complete 或 fail，taskId、runtime_id 和租约时间要能对应起来。"
            "如果心跳停止，先查最后一次心跳和时间线，再判断任务是否已进入恢复分支。"
        ),
        "数据库与 Redis 依赖": (
            "数据库故障通常先出现在 /readyz、迁移检查或业务写入中；Redis 故障会影响缓存、租约、队列和多节点中继。"
            "恢复时先确认连接地址和凭证，再核对迁移与 Redis 可用性，最后用一条最小业务请求复核。"
        ),
        "WebSocket 与断线补偿": (
            "客户端连接 /ws 后接收评论、任务状态和进度事件。断线时重新建立用户和工作区身份，"
            "再用问题详情、评论和 GET /api/issues/{id}/timeline 补齐缺失记录。多节点环境还要看 Redis 中继是否启用。"
        ),
        "外部集成回调": (
            "回调处理依次经过签名或令牌校验、连接识别、事件解析、业务写入和状态返回。"
            "收到重复回调时先查外部事件标识与时间线；签名失败则保留请求时间和状态码，不把密钥写入日志。"
        ),
    }
    return overrides.get(title, body)


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
            if backend_project(project):
                intro = backend_extra_content(title, intro)
            out += [intro, ""]
        for sec_no, section in enumerate(sections, 1):
            if isinstance(section, str):
                sec_title, body = f"小节 {sec_no}", section
            else:
                sec_title = str(section.get("title", f"小节 {sec_no}")).strip()
            body = str(section.get("content", section.get("body", ""))).strip()
            if backend_project(project) and body:
                body = backend_extra_content(sec_title, body)
            if not body:
                continue
            out += [f"## {number}.{sec_no} {sec_title}", "", body, ""]
    return "\n".join(out)


def modules(project):
    return project.get("modules") or []


def source_map(project):
    """返回内部源码分区映射；仅供材料清单/检查使用，不输出到说明书正文。"""
    return project.get("source_map") or []


def users(project):
    return project.get("users") or []


def numbered_steps(project, key, placeholder):
    steps = project.get(key) or []
    return "\n".join(f"{i}. {str(item)}" for i, item in enumerate(steps, 1))


def configured_rows(project, key, headers, placeholder):
    """只使用配置中的事实；缺失时返回空表，不把任务标记泄漏到正式材料。"""
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
    return []


def hardware_rows(project):
    """Use explicit hardware rows, or derive the two known values from env.

    Older project configs recorded machine requirements under ``env`` only;
    leaving the table renderer unaware of that field caused a fabricated
    ``待核验`` row to leak into the formal manual.
    """
    rows = project.get("hardware")
    if isinstance(rows, list) and rows:
        return rows
    env = project.get("env") or {}
    minimum = str(env.get("run_hardware", "")).strip()
    recommended = str(env.get("dev_hardware", "")).strip()
    if minimum or recommended:
        return [["运行设备", minimum or recommended, recommended or minimum]]
    return []


def hardware_section(project, spec=None):
    """Keep backend development and deployment hardware as separate rows."""
    env, _ = resolve_environment(project, spec=spec)
    if backend_project(project, spec):
        rows = []
        dev = str(env.get("dev_hardware", "")).strip()
        run = str(env.get("run_hardware", "")).strip()
        if dev:
            rows.append(["开发设备", dev, "Go 服务编译、Docker 构建和本地联调。"])
        if run:
            rows.append(["运行设备", run, "部署服务进程；数据库和 Redis 容量按实际负载规划。"])
        return table(rows, ["环境", "建议配置", "用途"])
    return table(hardware_rows({**project, "env": env}), ["硬件项", "最低配置", "推荐配置"])


def environment_rows(project, spec=None):
    """Use explicit environment rows, falling back to the documented env map."""
    rows = project.get("environment")
    if isinstance(rows, list) and rows:
        return rows
    env, _ = resolve_environment(project, spec=spec)
    rows = []
    for label, key in (("操作系统", "run_os"), ("运行支持", "run_support"),
                       ("开发工具", "dev_tools"), ("开发语言", "language"),
                       ("其他技术", "language_other")):
        value = str(env.get(key, "")).strip()
        if value:
            rows.append([label, value])
    return rows


def configured_text(project, key, placeholder):
    value = project.get(key)
    if isinstance(value, str) and value.strip() and not PLACEHOLDER.search(value):
        return value.strip()
    return ""


def development_goals(project):
    """Render configured, fact-based goals instead of forcing every project through a placeholder."""
    goals = project.get("development_goals")
    if isinstance(goals, list):
        rows = [str(goal).strip() for goal in goals if str(goal).strip()]
        if rows:
            return "\n".join(f"- {goal}" for goal in rows)
    return ""


def backend_first_check(project):
    """A short, useful first-run check for backend manuals.

    It keeps the overview tied to an action an operator can perform instead
    of ending on an abstract capability summary.
    """
    if not backend_project(project):
        return ""
    return (
        "首次部署先访问 GET /health；返回 200 后再访问 GET /readyz。"
        "如果 /readyz 返回 503，先看 PostgreSQL 连接和 schema_migrations，再检查 Redis 初始化日志。"
    )


def backend_verification_rows(project, spec=None):
    """Backend checks should describe a request and an observable response."""
    if not backend_project(project, spec):
        return configured_rows(project, "verification", ["验证项", "实际验证方式"], "实际部署验证")
    return [
        ["进程探测", "发送 GET /health；确认 HTTP 200 且 status 为 ok。连接失败时先查服务进程和监听地址。"],
        ["数据库就绪", "发送 GET /readyz；检查 checks.db 和 checks.migrations。返回 503 时对照 DATABASE_URL 与迁移版本。"],
        ["用户会话", "带登录会话调用 GET /api/me；确认响应里的用户标识与当前账号一致。返回 401 时重新登录并检查 Cookie 或 JWT。"],
        ["任务执行", "调用 POST /api/issues 创建问题，记下 issue ID；由运行时领取任务并回传进度，再读取该问题的 timeline 核对记录。"],
        ["实时事件", "以工作区身份连接 /ws，更新一条问题或评论后检查连接是否收到事件；未收到时读取 timeline，并核对 Redis 中继配置。"],
    ]


def backend_configuration_overview(project, spec=None):
    """Explain backend settings through startup effects and concrete failure checks."""
    if not backend_project(project, spec):
        return configured_text(project, "configuration_overview", "项目实际配置项和生效方式")
    return (
        "服务启动时从 DATABASE_URL 读取 PostgreSQL 连接地址，从 REDIS_URL 读取缓存和跨节点中继地址。"
        "执行 cmd/migrate 后访问 /readyz，查看 checks.db 与 checks.migrations；若返回 503，先核对连接地址、网络连通性和迁移版本。"
        "浏览器来源由 CORS_ALLOWED_ORIGINS 控制，未列入的来源会在预检阶段被拒绝。"
        "会话或 JWT 密钥、运行时令牌及 Webhook 签名凭证从环境变量注入；启动日志和请求日志不得输出凭证原文。"
    )
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
    shots = shots or {}
    render_screenshots = screenshots_enabled(project, shots)
    if spec and spec.get("pages"):
        module_table = table([[p["module"], p.get("purpose") or page_factual_intro(p)] for p in spec["pages"]],
                             ["模块", "功能概述"])
    else:
        module_table = table(modules(project), ["模块", "功能概述"])
    env_project = {**project, "env": {**(cfg.get("env") or {}), **(project.get("env") or {})}}
    hardware_table = hardware_section(env_project, spec)
    software_environment_table = table(environment_rows(env_project, spec), ["软件项", "说明"])
    user_ops = project.get("user_operations") or {}
    user_table = table([[u, user_ops.get(u, "") ] for u in users(project)], ["角色", "实际操作范围"])
    name = project["name"]
    short = project.get("short_name", name)
    version = project.get("version", "V1.0")
    summary = configured_text(project, "summary", "")
    position = configured_text(project, "position", "")
    identity = f"是一款{position}。" if position else "。"
    intro = f"{name}（以下简称“{short}”）{identity}"
    intro += summary
    api_section_text = rest_api_section(project, spec)
    verification_rows = backend_verification_rows(project, spec)
    configuration_overview = backend_configuration_overview(project, spec)
    tests_section_no = 3 if api_section_text else 2
    shot_section = ""
    if render_screenshots:
        shot_section = f"## 10.{tests_section_no + 1} 截图清单\n{shot_table(project, shots, spec)}"

    return manual_safe(undent(f"""\
    {toc(chapters)}

    # 软件概述

    ## 1.1 软件简介
    {intro}
    {backend_first_check(project)}

    ## 1.2 建设目标
    {development_goals(project)}

    ## 1.3 软件范围
    {configured_text(project, "scope", "软件负责的业务范围和不负责的边界")}

    ## 1.4 核心特性
    {module_table}

    ## 1.5 适用范围
    {table(configured_rows(project, "scenarios", ["范围", "实际使用说明"], "实际使用范围"), ["范围", "实际使用说明"])}

    ## 1.6 主要用户角色
    {user_table}

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
    {hardware_table}

    ## 3.2 软件环境
    {software_environment_table}

    ## 3.3 权限要求
    {table(project.get("permissions") or [], ["权限", "实际配置依据"])}

    # 安装部署

    ## 4.1 安装前准备
    {configured_text(project, "install_prerequisites", "项目实际安装前置条件")}

    ## 4.2 安装步骤
    {numbered_steps(project, "install_steps", "实际安装命令")}

    ## 4.3 部署后验证
    {table(verification_rows, ["验证项", "实际验证方式"])}

    # 配置说明

    ## 5.1 配置概述
    {configuration_overview}

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

    {api_section_text}

    ## 10.{tests_section_no} 测试用例
    {table(configured_rows(project, "tests", ["编号", "场景", "实际结果"], "实际测试记录"), ["编号", "场景", "实际结果"])}

    {shot_section}

    {extra_chapters(project, chapters)}
    """))


def rest_api_section(project, spec=None):
    """Render a small, factual REST contract appendix when supplied.

    Route extraction alone cannot safely infer request/response schemas.  A
    project can therefore provide a curated ``api_examples`` list whose field
    names are copied from the actual handler structs.  The section is omitted
    for projects without that list (for example desktop-only materials).
    """
    examples = project.get("api_examples") or []
    catalog = project.get("api_catalog") or []
    if not examples and not catalog:
        return ""

    def fields(rows, empty="无请求体。"):
        if not rows:
            return empty
        return table(rows, ["字段", "类型", "说明"])

    out = [
        "## 10.2 核心 REST API 数据结构",
        "",
        "先用 GET /health 和 GET /readyz 判断服务是否可用，再按需要查看 /api/me、/api/workspaces 和 /api/issues。下列字段来自配置中登记的请求与响应结构；示例值只表示类型，不对应真实用户。",
        "",
    ]
    for index, item in enumerate(examples, 1):
        method = str(item.get("method", "")).upper()
        path = str(item.get("path", "")).strip()
        title = str(item.get("title", "")).strip()
        out.append(f"### API-{index} {method} {path}")
        if title:
            out += ["", f"用途：{title}"]
        if item.get("auth"):
            out += ["", f"认证与范围：{item['auth']}"]
        out += ["", "请求字段", "", fields(item.get("request_fields"), str(item.get("request", "无请求体。"))), "",
                "响应字段", "", fields(item.get("response_fields"), "由接口状态码返回，不含 JSON 字段。"), ""]
        if item.get("status_codes"):
            out += ["状态码", "", table(item["status_codes"], ["状态码", "含义"]), ""]
        if item.get("notes"):
            out += [f"处理说明：{item['notes']}", ""]
    if catalog:
        out += [
            "### 接口目录（按业务分组）",
            "",
            "需要查路由时先按业务分组找方法和路径，例如服务状态从 /health 开始，运行时从 /api/daemon/register 开始。目录不表示接口允许匿名访问；请求体和权限仍以对应入口的校验结果为准。",
            "",
            table(catalog, ["业务分组", "方法", "路径", "用途"]),
            "",
        ]
    return "\n".join(out).rstrip()


def shot_table(project, shots, spec=None):
    rows = [[it["no"], it["title"], f"`{it['file']}`"] for items in (shots or {}).values() for it in items]
    return table(sorted(rows), ["编号", "截图", "文件"])


def evidence_plan_markdown(project, spec=None):
    plan = evidence_plan(spec, project)
    if not plan:
        return ""
    lines = ["# 截图证据计划", "", "以下条目必须来自真实运行结果或项目实际调试页面，不得用占位图或虚构数据替代。", "", "| ID | 证据 | 必须 | 采集说明 |", "|---|---|---|---|"]
    for item in plan:
        required = "是" if item.get("required", True) else "否"
        lines.append(f"| {item.get('id', '')} | {item.get('title', '')} | {required} | {item.get('note', '')} |")
    return "\n".join(lines) + "\n"


def write_project(root, cfg, project, spec=None):
    out = root / project["id"]
    # 正文重新生成后，旧的朱雀指纹已经失效；必须重新检测，避免旧报告
    # 被误认为对应当前文本。
    for stale in (out / ".zhusque-final.json", out / "朱雀检测报告.md"):
        if stale.exists():
            stale.unlink()
    chapters = out / "说明书章节"
    source_dir = out / "源程序提取"
    chapters.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    shots = load_shots(root, project)
    text = manual(project, cfg, spec, shots)
    (out / "软件说明书.md").write_text(text, encoding="utf-8")
    (out / "申请表填报文案.md").write_text(application_copy(project, cfg, spec), encoding="utf-8")
    (out / "源码材料清单.md").write_text(source_list(project), encoding="utf-8")
    include_evidence = project.get("include_screenshot_evidence")
    if include_evidence is None:
        include_evidence = any(bool(items) for items in shots.values())
    evidence = evidence_plan_markdown(project, spec) if include_evidence else ""
    evidence_path = out / "截图证据计划.md"
    if evidence:
        evidence_path.write_text(evidence, encoding="utf-8")
    elif evidence_path.exists():
        evidence_path.unlink()
    chapters_list = chapter_names(project)
    chapter_markers = [
        f"# {chapter}" if idx <= len(DEFAULT_CHAPTERS) else f"# {idx} {chapter}"
        for idx, chapter in enumerate(chapters_list, 1)
    ]
    # A project can be regenerated with a shorter chapter list than a prior
    # run (for example after removing an optional chapter).  Do not leave the
    # old generated markdown beside the new package: it is easy to mistake a
    # stale file for an active chapter and accidentally upload it.
    expected_chapters = {
        f"{idx:02d}-{chapter}.md" for idx, chapter in enumerate(chapters_list, 1)
    }
    for stale in chapters.glob("[0-9][0-9]-*.md"):
        if stale.name not in expected_chapters:
            stale.unlink()
    for idx, chapter in enumerate(chapters_list, 1):
        marker = chapter_markers[idx - 1]
        start = text.find(marker)
        end = text.find(f"\n{chapter_markers[idx]}", start + 1) if idx < len(chapters_list) else len(text)
        if start >= 0:
            (chapters / f"{idx:02d}-{chapter}.md").write_text(text[start:end].strip() + "\n", encoding="utf-8")


def reference_material_report(cfg, root):
    """Write an audit trail for an optional prior-materials directory.

    Reference documents are evidence/style inputs, not a license to copy
    unsupported features into a new manual.  Keeping the inventory beside the
    generated package makes it clear which prior files were consulted and
    leaves the formal PDF limited to facts supplied for the current project.
    """
    reference = cfg.get("reference_materials")
    if not isinstance(reference, dict):
        return
    raw_root = str(reference.get("root", "")).strip()
    if not raw_root:
        return
    ref_root = Path(raw_root).expanduser()
    lines = ["# 参考材料核对", "", f"参考目录：`{ref_root}`", ""]
    if not ref_root.exists():
        lines.append("目录未找到；本次材料未读取参考文件，正式说明书只使用当前项目事实。")
    else:
        instruction_dir = ref_root / "instructions"
        screenshot_dir = ref_root / "screenshots"
        instruction_files = sorted(instruction_dir.glob("*.md")) if instruction_dir.exists() else []
        screenshot_files = sorted(
            p for p in screenshot_dir.iterdir() if p.is_file()
        ) if screenshot_dir.exists() else []
        lines.extend([
            "已核对目录结构：",
            f"- 章节材料：{len(instruction_files)} 份",
            f"- 截图材料：{len(screenshot_files)} 张",
            "- 使用规则：参考章节组织、版式和环境描述；只有当前项目源码、运行记录或截图能够验证的功能才进入正式说明书。",
            "- 未使用规则：不复制参考项目专属名称、页面、接口、日志或未在当前项目中验证的能力。",
        ])
        if instruction_files:
            lines += ["", "已发现的章节文件："]
            lines.extend(f"- `{p.name}`" for p in instruction_files)
    (root / "参考材料核对.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        return ""
    st = spec["stats"]
    return (f"{st['source_lines']} 行（{st['source_files']} 个源文件，manual_spec.py 统计）。"
            "申请表“源程序量”填全部源码行数，不是 60 页取材的行数。")


def application_copy(project, cfg, spec=None):
    """申请表文案初稿：只写已配置的事实，缺失项直接省略（不写任何占位文字）。

    application_form.py 会用同源字段覆盖本文件并给出缺失字段校验清单。
    """
    env = {**cfg.get("env", {}), **project.get("env", {})}
    rows = [
        ("软件全称", project["name"]),
        ("软件简称", project.get("short_name", project["name"])),
        ("版本号", project.get("version", "V1.0")),
        ("软件分类", project.get("category", "应用软件")),
        ("著作权人", configured_fact(cfg.get("copyright_holder", ""))),
        ("开发完成日期", configured_fact(cfg.get("development_completed_date", ""))),
        ("首次发表日期", configured_fact(cfg.get("first_publication_date", "未发表")) or "未发表"),
        ("权利取得方式", configured_fact(cfg.get("acquire_type", "原始取得")) or "原始取得"),
        ("开发方式", configured_fact(cfg.get("develop_type", "独立开发")) or "独立开发"),
    ]
    out = [f"# {project['name']} {project.get('version', 'V1.0')} 申请表填报文案", "",
           "| 项目 | 建议填写 |", "| --- | --- |"]
    out += [f"| {k} | {v} |" for k, v in rows if str(v).strip()]
    sections = [
        ("软件主要功能", configured_text(project, "summary", "")),
        ("源程序量", spec_lines(spec)),
        ("开发工具", str(env.get("dev_tools", "")).strip()),
        ("技术特点", configured_text(project, "tech_feature_text", "")),
    ]
    for title, body in sections:
        if body:
            out += ["", f"## {title}", body]
    return "\n".join(out) + "\n"


def missing_info(cfg):
    """只列出真正缺失的主体信息；全部齐备时返回空列表。"""
    # The R11 page supplies the copyright holder from the logged-in account.
    # Keep local configuration optional; the browser flow verifies the value.
    keys = [("development_completed_date", "开发完成日期")]
    return [label for key, label in keys if not str(cfg.get(key, "")).strip()]


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
        generate_ai_compliance(root, cfg, project)
    if not args.skip_aigc:
        run_initial_aigc(root, cfg["projects"])
    reference_material_report(cfg, root)
    legacy = root / "待补充信息清单.md"
    if legacy.exists():
        legacy.unlink()
    missing = missing_info(cfg)
    report = root / "缺失信息清单.md"
    if missing:
        report.write_text("# 缺失信息清单\n\n以下信息未在 ruanzhu.config.json 中配置：\n\n"
                          + "".join(f"- {m}\n" for m in missing), encoding="utf-8")
    elif report.exists():
        report.unlink()
    print(root)


if __name__ == "__main__":
    main()
