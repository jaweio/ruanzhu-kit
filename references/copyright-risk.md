# 版权风险检查与开源痕迹清除（Step 5 细则）

> 硬性要求：**申报材料（源程序、说明书、申请表、填表文案）中一律不得出现三类内容：① 开源协议 ② 仓库/托管地址 ③ 引用来源。**
> 业务用语不在清除范围：Star 评分、Issue 工单、`fork()`、PR、贡献者、社区、GitHub 登录、许可证管理、开源节流等原样保留。
> 工具：`copyright_check.py`（检查）、`oss_scrub.py`（清除说明书类文本）、`generate_source_docx.py`（提取源程序时自动清除 + 跳过第三方文件）。全部本地离线。

---

## 1. 两类代码，两种处理

| 代码 | 判定依据 | 处理 |
| --- | --- | --- |
| **自有代码**（含自己先开源、后上架的项目） | 文件头版权人是著作权人，或在 `self_aliases` 中（GitHub/Gitee 账号、组织名、英文名、团队名）；无版权行的文件也按自有处理 | 提取时**自动清除**：文件开头第一个注释块中的许可证/版权声明；含协议文本或引用标记的注释行；代码和注释里的仓库、徽章、博客/问答地址（注释里其余文字保留，如 `// issue #12: 分页修复`）；`git clone` 等依赖仓库地址的命令 |
| **第三方代码** | 版权人不是自己；`node_modules/`、`vendor/`、`dist/` 等路径；压缩代码；开源脚手架特征 | 提取时**自动跳过**，整份文件不进入材料；不删除他人的版权声明 |

第三方代码不能靠删声明变成自有代码，所以用“跳过”而不是“清除”——结果一样：材料里不会出现任何开源信息。

**发表状态一律按“未发表”处理。** 申报的是上架版本，与开源的参考代码有本质区别；`first_publication_date` 默认“未发表”，auto-fill 的 `published` 默认 `false`。源程序材料必须从申报的上架版本中取，不要从开源参考仓库取。

## 2. 配置

```json
{
  "copyright_holder": "杭州智租科技有限公司",
  "first_publication_date": "未发表",
  "self_open_source": true,
  "self_aliases": ["ZhiRent", "zhirent", "ZhiRent Team"],
  "projects": [{ "...": "...", "redact": true, "scrub_open_source": true }]
}
```

| 字段 | 作用 |
| --- | --- |
| `self_open_source` | 项目是自己开源的。为真时，本地 git 远程里的仓库所有者也自动算作自有 |
| `self_aliases` | 自有身份的其他写法。LICENSE 写的是 “ZhiRent Team”、仓库在 `github.com/zhirent`，就把这两个填进来 |
| `redact` | 提取源程序时脱敏密钥、手机号、邮箱、内网 IP（默认开） |
| `scrub_open_source` | 提取源程序时清除自有代码的开源痕迹（默认开） |

没填 `self_aliases` 时，自己项目的 LICENSE 会被当成“他人版权”，文件会被跳过、项目层报中风险——报告里会提示补这个字段。

## 3. 使用流程

```bash
S=<skill目录>/scripts
C=soft-copyright-materials/ruanzhu.config.json

# ① 选好 source_files 后：项目层 + 取材层预检
python3 $S/copyright_check.py --config $C --repo <上架版本源码目录> --skip materials

# ② 提取源程序：自动跳过第三方文件、清除自有开源痕迹、脱敏
python3 $S/generate_source_docx.py --config $C --repo <上架版本源码目录>
#    终端和《源程序DOCX生成报告.md》会列出跳过的文件和可用行数；行数不足就补选自研文件

# ③ 说明书 / 申请表 / auto-fill 文案：先预览再写回（留 .bak）
python3 $S/oss_scrub.py --config $C
python3 $S/oss_scrub.py --config $C --apply

# ④ 闸门：三层全查，产出层任何开源痕迹都是高风险
python3 $S/copyright_check.py --config $C --repo <上架版本源码目录> --fail-on high

# ⑤ PDF 渲染后再跑一次 ④（会读取 PDF 文本）
```

### 清除范围（oss_scrub.py 与源程序提取共用一套规则）

| 类别 | 命中即清除 | 不清除（业务用语） |
| --- | --- | --- |
| ① 开源协议 | `SPDX-License-Identifier`、Licensed under、MIT/Apache/GPL/BSD/MPL/木兰 协议或 License、许可协议正文（Permission is hereby granted…）、`@license`；标题为“开源协议 / 许可证 / License”的整节 | “许可证管理”“营业许可证”等业务标题和句子 |
| ② 地址 | GitHub/Gitee/GitLab/Bitbucket/GitCode 等仓库地址和 `git@` 地址、shields 徽章、star-history、npm/PyPI 包页、`*.github.io` 文档站；“已开源 / 开源地址 / 源码托管在 Gitee / GitHub 仓库 / 欢迎 Star”等声明 | “GitHub 账号授权登录”“Star 数”“开源节流” |
| ③ 引用 | 参考自 / 引用自 / 来源： / 转载 / 摘自 / 改编自 / 借鉴自、forked from、based on X、adapted from、ported from、inspired by、原作者 / 原项目；CSDN、StackOverflow、掘金、博客园、知乎等地址；提到 RuoYi、vue-element-admin 等开源项目名的句子；标题为“致谢 / Acknowledgements / Credits / 参考资料 / Star History”的整节 | “参考值”“数据来源为房东录入”“Issue 工单”“fork 子任务”“PR 审核”“贡献者积分”“社区”“更新日志” |

文档按句删除（句中出现上述任一项，整句删掉），徽章行和只有地址的行整行删掉，`[文字](地址)` 只保留文字，地址删掉后残留的“详见 / 参见”一并清掉。代码块按源程序规则处理。

规则改动后运行 `python3 scripts/oss_selftest.py`（50 个保留/删除用例）回归。

清除后如果某段只剩一两句，读起来断，按 AIGC 任务单的要求补写操作内容即可（Step 6）。

## 4. 检查项

### 4.1 项目层（`--repo`）

| 检查 | 自有开源（已配置） | 未识别 |
| --- | --- | --- |
| LICENSE / COPYING / NOTICE | 低：自动清除 | 中（GPL 类高）：提示补 `self_aliases` 或核实来源 |
| LICENSE 版权人 ≠ 著作权人及别名 | — | 高：可能是他人项目 |
| 包清单 `license` / `repository` | 低 | 中 |
| 开源脚手架特征（RuoYi、JeecgBoot、芋道、Vben、vue-element-admin、Ant Design Pro 等） | 高 | 高：只申报自研部分 |
| git 远程 | 所有者在别名中：低 | 中：确认是自己的仓库还是他人项目 |
| `upstream` 远程、首个提交来自模板 | 高 / 中 | 高 / 中 |
| 提交者名单 | 低：核对均为本方人员 | 低 |

### 4.2 取材层（`source_files`）

| 检查 | 级别 |
| --- | --- |
| 同一文件被多份软著取材 | 高 |
| 第三方路径、压缩代码、他人许可证头或版权声明、脚手架代码 | 中（提取时自动跳过，需补选文件） |
| 自有许可证头、自有仓库链接 | 低（提取时自动清除） |
| 他人仓库链接、博客/问答来源、“参考自 / forked from”注释 | 中：提取时自动删除，但要确认代码是否照搬自该处，是则换文件 |
| 工具生成代码、`.d.ts` 声明文件、AI 生成标记 | 中 / 低 |
| 密钥 | 高（提取时脱敏，仍须轮换） |
| 手机号 / 邮箱 / 内网 IP / 身份证号 | 低（提取时脱敏） |

### 4.3 产出层（`output_root`）

扫描说明书 md/pdf、申请表、auto-fill 配置、源程序 docx/pdf：

| 检查 | 级别 |
| --- | --- |
| 仓库地址、徽章 / 包平台地址 | 高 |
| 开源协议、开源声明、引用标记（源程序按注释规则，说明书按句子规则） | 高 |
| 开源脚手架名称 | 高 |
| 密钥 | 高 |
| 说明书中的手机号、邮箱 | 中 |
| 软件全称缺失、auto-fill 名称不一致、申请表著作权人不一致 | 高 |
| 版本号缺失 | 中 |

## 5. Claude 的处理纪律

1. 申报材料里不留开源协议、仓库地址、引用来源；业务用语（Star、Issue、fork、PR 等）不动。发现后用上面的工具清除并重新生成，不手工逐处修改 PDF。
2. 自有开源项目：先确认 `self_open_source` 和 `self_aliases` 已配置，再提取；发表状态按“未发表”，源程序取自上架版本。
3. 第三方代码：不删除他人声明，不改写后冒充自研；换文件。
4. 项目基于他人开源脚手架：先向用户说明，只申报自研部分。
5. 高风险清零才能进入 Step 7；报告里的提交者姓名等只在本地留档。

## 6. 已知局限

- 只能识别留下痕迹的第三方代码；删过注释、改过命名的复制代码，需要 scancode-toolkit、FOSSology 等工具进一步排查。
- 脚手架特征库覆盖常见国产开源项目，其他项目可在 `copyright_check.py` 的 `SCAFFOLDS` 中补充。
- 清除范围限定在协议、地址、引用三类，Star、Issue、fork、PR、贡献者、社区等业务词不动；遇到新的误删或漏删，把句子加进 `oss_selftest.py` 再调规则。`oss_scrub.py` 默认先预览 diff，确认后再 `--apply`。
