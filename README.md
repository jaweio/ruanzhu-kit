# 软著工具箱 · ruanzhu-kit

用于 Codex / Claude 的中文软件著作权材料工作流：分析项目、生成说明书、提取源程序、整理申请表字段，并通过用户授权的浏览器填写 R11 表单、上传 PDF、保存草稿。

[使用规范](SKILL.md) · [版本记录](CHANGELOG.md) · [下载发布包](https://github.com/jaweio/ruanzhu-kit/releases) · [反馈问题](https://github.com/jaweio/ruanzhu-kit/issues)

## 功能

- 按真实源码整理模块、界面文字和操作素材，支持多份材料的取材隔离。
- 生成说明书 Markdown/PDF、源码 DOCX/PDF，整理截图和章节目录。
- 本地检查占位符、文本长度、敏感信息、来源线索和模板化文风。
- 汇总申请字段、生成填表操作计划，支持浏览器扩展和 Computer Use。
- 上传说明书与源程序 PDF，回读核对后保存草稿。正式提交由用户完成。
- 输出材料进度看板；提供版本化发布包和 Git 更新工具。

## 安装

需要 Python 3.10+ 和 Git。以下命令安装完整仓库，后续可直接更新。

Codex / 通用 agent skills 目录：

```bash
git clone https://github.com/jaweio/ruanzhu-kit.git ~/.agents/skills/ruanzhu-kit
```

Claude Code：

```bash
git clone https://github.com/jaweio/ruanzhu-kit.git ~/.claude/skills/ruanzhu-kit
```

已有同名本地 skill 时，先把旧目录改名备份，或选择另一个安装目录；不要直接覆盖本地修改。安装后重新开启会话，让宿主识别 `SKILL.md`。

也可下载 Release 中的 `ruanzhu-kit.skill`；它是带 `ruanzhu-kit/` 顶层目录的 ZIP。支持 `.skill` 的客户端可导入；其他客户端解压到其 skills 目录。压缩包安装的升级方式是备份旧目录后导入新版本。

## 每次使用前自动检查更新

从 v1.0.1 起，SKILL.md 要求 agent 在每个新任务开始时自动运行 `scripts/check_update.py --json`。每次查询 GitHub 最新正式 Release，发现新版就提示版本和链接；默认超时 4 秒，断网或限流不阻塞任务。Git 安装和 `.skill` 解压安装均可检查。

检查不会自动安装新版或覆盖本地文件。无新版时静默继续，有新版时也可继续完成当前任务。此能力依赖客户端遵循 SKILL.md；直接运行业务脚本不会触发它。v1.0.0 用户需要先升级一次才能获得此步骤。

可手动验证：

```bash
python3 <skill目录>/scripts/check_update.py --json
```

## 安装新版

用户选择更新后，Git 安装执行：

```bash
python3 ~/.agents/skills/ruanzhu-kit/scripts/manage_install.py update --dest ~/.agents/skills/ruanzhu-kit
```

Claude 用户将路径换为 `~/.claude/skills/ruanzhu-kit`。更新工具检查远端、main 分支和本地改动，只允许快进更新；遇到冲突会停止，不会重置或覆盖用户文件。它不会在后台自行更新。

也可手动执行 `git -C <安装目录> pull --ff-only`。版本号位于 `VERSION`，每次发布的变化记录在 `CHANGELOG.md`。需固定版本时可在独立克隆中 `git checkout v1.0.0`，恢复 `main` 后才能使用更新工具。

## 依赖

基础分析和文本处理使用 Python 标准库；生成源码 DOCX 需要：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

说明书 PDF：Pandoc + Chrome/Chromium。源码 DOCX 转 PDF：LibreOffice。页数检查建议安装 Poppler（pdfinfo）。工具优先读取 `RUANZHU_CHROME`、`RUANZHU_PDFINFO`、`RUANZHU_SOFFICE` 环境变量，其次检查常见路径和 PATH。截图还需对应平台的工具和权限，详见 SKILL.md。

浏览器填表优先使用宿主提供的浏览器扩展或 Computer Use，复用用户已登录的会话。备用脚本 `scripts/auto-fill/auto-fill.js` 依赖 Node.js 和 Playwright；官网改版后可能需要调整定位器，不能保证直接运行适配所有页面。

## 使用

在项目会话中请求：

> 使用 ruanzhu-kit，分析当前项目，生成一份软著材料。名称、版本、著作权人、日期采用我提供的真实资料。根据实际代码写说明书，完成后先给我核对。

已备好材料时：

> 使用 ruanzhu-kit，在当前已登录的版权中心填写申请表，上传我指定的说明书和源程序 PDF，核对后保存草稿。

命令行初始化示例（将 `<skill目录>` 换为安装路径）：

```bash
python3 <skill目录>/scripts/create_config.py --project-name "我的项目" --output soft-copyright-materials/ruanzhu.config.json
python3 <skill目录>/scripts/manual_spec.py --repo . --out soft-copyright-materials/说明书素材.json
```

补全真实资料和素材后，按 [SKILL.md](SKILL.md) 运行材料生成、检查、PDF 渲染和填表流程。项目材料应保存在业务项目目录，不要提交到本工具仓库。

## 当前版本的边界

v1.0.0 基于 2026-09-20 的本地版本发布，只增加开源分发支持、移除本机工具路径并修复 `--check` 参数解析。保留既有业务脚本；以下旧规则和能力限制需要人工核实：

- 旧文档存在随机选择日期、统一填写未发表的表述；不能作为实际申报依据。日期、发表状态和权利范围应来自真实资料，未知时留待用户补充。
- 来源检查是规则扫描，不能证明代码权属；不能因缺少声明便认定为自研，也不能用清理功能掩盖来源或删除必须保留的许可声明。
- AIGC 分数只反映本地规则中的文风特征，不能识别生成模型，也不保证与外部检测一致。所附样本标签是历史校准记录，不代表本次发布重新验证的准确率。
- 默认 PDF 仍采用 Letter、固定十章目录、较宽行距和右下角页码；未自动实现底部居中页码及所有小节跳转。
- 脚本与说明文件的输出命名可能不同，例如 PDF 渲染实际生成 `软件文档.pdf`；填写时应以实际生成并核对过的文件为准。
- 自动化无法替代对材料事实的核对；登录、验证码和最终提交由用户操作。

## 开发与发布

```bash
python3 -m unittest discover -s tests -v
python3 scripts/oss_selftest.py
python3 scripts/aigc_calibrate.py
python3 scripts/package_release.py
```

最后一条命令在 `dist/` 生成带版本号的 `.skill`、通用下载名 `.skill` 和 SHA-256 校验文件。维护者更新 `VERSION` / `CHANGELOG.md`，提交后创建同名 `vX.Y.Z` Git 标签，再在 GitHub Release 上传这些产物。安装用户运行更新命令即可拉取后续 main 分支版本。

## 许可证

MIT，见 [LICENSE](LICENSE)。许可证适用于本仓库工具；用户项目和生成材料的权利归属不因使用本工具改变。
