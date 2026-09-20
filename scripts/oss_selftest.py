#!/usr/bin/env python3
"""oss_scrub 回归自测：改 oss_scrub.py / copyright_check.py 的规则后必跑。

清除范围只有三类：开源协议、仓库/托管地址、引用来源。业务用语（Star 评分、Issue 工单、
fork()、PR、贡献者、社区、GitHub 登录、许可证管理、开源节流……）必须原样保留。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oss_scrub import scrub_code, scrub_markdown  # noqa: E402

TOKENS = ["ZhiRent", "zhirent"]

# ---------------------------------------------------------------- 文档：必须保留
DOC_KEEP = [
    "租客可给房源打 1 到 5 星，Star 数在房源卡片右上角显示。",
    "租客提交 Issue 工单后，房东在“工单中心”处理；工单可 fork 为子任务，处理完成后提交 PR 审核记录。",
    "登录页支持微信、GitHub 账号授权登录，GitHub 授权失败时提示重新登录。",
    "社区版房东的贡献者积分按月结算，本月开源节流方案由财务配置。",
    "房东上传营业许可证，系统校验有效期。",
    "## 7.5 许可证管理",
    "## 社区",
    "## 更新日志",
    "## 贡献者积分",
    "系统基于角色的权限设计，参考值由管理员配置。",
    "合同到期前 30 天提醒，详见“合同管理”。",
    "接口遵循 RESTful 规范，数据来源为房东录入。",
]
# ---------------------------------------------------------------- 文档：必须删除
DOC_DROP = [
    "本项目已在 GitHub 开源。",
    "源码托管在 Gitee 仓库。",
    "本系统的权限设计参考自 RuoYi。",
    "部分工具函数摘自 CSDN 博客。",
    "项目采用 MIT 协议。",
    "本项目遵循 Apache-2.0 开源协议。",
    "详见 https://blog.csdn.net/x/article/1 。",
    "源码地址：https://gitee.com/zhirent/zhirent",
    "[![stars](https://img.shields.io/github/stars/a/b)](https://github.com/a/b)",
    "Forked from someone/rent-template.",
    "欢迎 Star 支持。",
    "权限模块基于 vue-element-admin 实现。",
]
DOC_DROP_SECTIONS = ["## 开源协议", "## License", "## 致谢", "## Acknowledgements", "## Star History", "## 参考资料"]

# ---------------------------------------------------------------- 代码
CODE_KEEP = [
    "// 评分：star 取值 1-5",
    "export function rate(star: number) { return star }",
    "// Issue 工单：fork 出子工单",
    "export function forkIssue(issueId: number) { return { parent: issueId } }",
    "// PR 审核记录，contributors 列表",
    "// GitHub OAuth 登录回调",
    "export const githubLogin = () => fetch('/oauth/github')  // github 授权",
    "// 许可证有效期校验",
    "#include <stdio.h>",
]
CODE_DROP = [
    "// Licensed under the MIT License",
    "// SPDX-License-Identifier: Apache-2.0",
    "// 参考自 https://stackoverflow.com/questions/123",
    "// adapted from lodash debounce",
    "# forked from someone/tool",
    "// 代码摘自网络",
    "// 欢迎 Star",
]
CODE_EDIT = [  # (原行, 期望结果)
    ("// issue #12: 分页修复，详见 https://github.com/zhirent/zhirent/pull/34", "// issue #12: 分页修复"),
    ("const doc = 'https://gitee.com/zhirent/zhirent/wikis'", "const doc = ''"),
]
HEADER = """/**
 * Copyright (c) 2025 ZhiRent Team
 * SPDX-License-Identifier: MIT
 */
"""
FOREIGN_HEADER = """/*! dayjs | Copyright (c) 2018 iamkun | MIT License */
"""


def main():
    fails = []
    body = "# 功能模块\n\n" + "\n\n".join(DOC_KEEP + DOC_DROP) + "\n\n" + \
        "\n\n".join(f"{h}\n\n这一节的内容。" for h in DOC_DROP_SECTIONS) + "\n"
    out, _ = scrub_markdown(body)
    for k in DOC_KEEP:
        if k not in out:
            fails.append(f"文档误删：{k}")
    for d in DOC_DROP + DOC_DROP_SECTIONS:
        if d in out:
            fails.append(f"文档漏删：{d}")
    if "这一节的内容" in out:
        fails.append("文档漏删：协议/致谢类章节正文")

    code = "\n".join(CODE_KEEP + CODE_DROP + [a for a, _ in CODE_EDIT])
    lines, _ = scrub_code(code, TOKENS)
    for k in CODE_KEEP:
        if k not in lines:
            fails.append(f"代码误删：{k}")
    for d in CODE_DROP:
        if d in lines:
            fails.append(f"代码漏删：{d}")
    for src, want in CODE_EDIT:
        if want not in lines:
            fails.append(f"代码处理不符：{src} → 期望 {want}")

    lines, st = scrub_code(HEADER + "export class A {}\n", TOKENS)
    if not st["header"] or any("SPDX" in l or "Copyright" in l for l in lines):
        fails.append("自有许可证头未删除")
    lines, st = scrub_code(FOREIGN_HEADER + "export const d = 1\n", TOKENS)
    if st["header"]:
        fails.append("他人版权头被删除（应保留，由提取流程整体跳过该文件）")

    total = len(DOC_KEEP) + len(DOC_DROP) + len(DOC_DROP_SECTIONS) + len(CODE_KEEP) + len(CODE_DROP) + len(CODE_EDIT) + 2
    if fails:
        print("\n".join(fails))
        print(f"\n失败 {len(fails)} / {total}")
        sys.exit(1)
    print(f"通过 {total} / {total}")


if __name__ == "__main__":
    main()
