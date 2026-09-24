# 软著工具箱 · ruanzhu-kit

用于 Codex / Claude 的中文软件著作权材料工作流：分析项目、生成说明书、提取源程序、整理申请表字段，并通过用户授权的浏览器填写 R11 表单、上传 PDF、保存草稿。

[使用规范](SKILL.md) · [版本记录](CHANGELOG.md) · [下载发布包](https://github.com/jaweio/ruanzhu-kit/releases) · [反馈问题](https://github.com/jaweio/ruanzhu-kit/issues)

## 功能

- 按真实源码整理模块、界面文字和操作素材，支持多份材料的取材隔离。
- 生成说明书 Markdown/PDF、源码 DOCX/PDF，整理截图和章节目录。
- 源程序鉴别材料默认裁剪普通注释、Go/Python/JS 等导入块、C/C++ include 和连续空行，只保留包声明与核心实现；原项目代码不改写，可用 `--keep-comments` / `--keep-imports` 恢复。
- 提供本地源程序材料可视化预览：查看行数变化、裁剪统计、第三方跳过情况和脱敏代码样本。
- 结合项目源码生成演示数据方案，供浏览器/Computer Use 在本地运行项目中创建真实业务语义的数据后截图。
- 可选分析/启动本地前后端会话，按显式 API 适配器预览、写入并回滚演示数据；默认不启动、不写库。
- 支持软著专用分支/独立工作树和源码重叠检查，主分支不自动修改、不自动推送。
- 支持截图清单完整性校验，提前发现缺图、空图和未覆盖模块。
- 后端项目自动从源码提取接口方法/路径/文件/行号，并生成真实证据计划；校验 Knife4j/OpenAPI、成功响应、4xx 错误响应和运行日志截图，禁止用模板页替代。
- 本地检查占位符、文本长度、敏感信息、来源线索和模板化文风。
- AIGC 文风报告额外统计“可以/系统/模块”等高频词，识别“系统优势/核心价值”等通用章节和“整套业务闭环是完整的”等生成式表达。
- 朱雀正式检测（必需闸门）：Key 只绑定到本机 macOS Keychain，未绑定时提示用户前往腾讯 EdgeOne Makers 自行生成；用户两次明确拒绝后才记为“用户豁免”放行。
- Jev 仍是实验性可选代码，默认关闭、不联网，也不参与填表流程；当前主流程只使用本地版权/AIGC/材料清单闸门。
- 汇总申请字段、生成填表操作计划，支持浏览器扩展和 Computer Use。
- 上传说明书与源程序 PDF，回读核对后保存草稿。著作权人通常由已登录的版权中心账户带入，工具不要求在本地配置重复填写，只在确认页回读核对。正式提交由用户完成。
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

### 自动发布

向 GitHub 推送 `v*` 格式的版本标签后，`.github/workflows/release.yml` 会自动创建对应的 GitHub Release。版本提交、标签和 Release 建议按以下顺序完成：更新 `VERSION` 与 `CHANGELOG.md`，提交后创建并推送同名标签，例如 `git tag -a v1.0.4 -m 'Release v1.0.4' && git push origin main --follow-tags`。

## 依赖

基础分析和文本处理使用 Python 标准库；生成源码 DOCX 需要：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

说明书 PDF 和源程序 PDF：Pandoc/源码 HTML + Chrome/Chromium。源程序 DOCX 仍由 Python `python-docx` 生成，作为可编辑稿，不再作为 PDF 转换中间文件；不要求安装 LibreOffice、WPS 或 Microsoft Word。`pypdf` 用于 PDF 文本和页数回读，页数检查建议同时安装 Poppler（pdfinfo），没有时工具会使用 PDF 对象回退统计。Chrome/Chromium 优先读取 `RUANZHU_CHROME`，截图还需对应平台的工具和权限，详见 SKILL.md。

纸面材料照片转 A4 PDF 使用 Pillow + ReportLab，包含在 `requirements.txt`。处理默认保留照片颜色，只做纸张范围和透视校正；白底增强必须显式选择 `--whiten-background`。

```bash
python3 scripts/photo_to_a4_pdf.py \
  "/path/to/纸面照片.jpg" \
  --output "/path/to/材料_A4.pdf" \
  --corners 238 313 3990 100 4048 5474 285 5577
```

示例数字只适用于对应照片；使用时须根据当前图片重新确认四角坐标。

生成前先运行本机预检，避免换主机后才发现 PDF 无法读取或中文字体缺失：

```bash
python3 <skill目录>/scripts/preflight.py --config <材料目录>/ruanzhu.config.json --strict
```

预检只读本机环境，不启动项目、不上传材料；备用 Playwright 填表脚本另加 `--include-browser`。

浏览器填表优先使用宿主提供的浏览器扩展或 Computer Use，复用用户已登录的会话。备用脚本 `scripts/auto-fill/auto-fill.js` 依赖 Node.js 和 Playwright；官网改版后可能需要调整定位器，不能保证直接运行适配所有页面。

## 使用

在项目会话中请求：

> 使用 ruanzhu-kit，分析当前项目，生成一份软著材料。名称、版本和日期采用我提供的真实资料；著作权人以已登录版权中心账户为准，生成后按页面回读核对。根据实际代码写说明书，完成后先给我核对。

已备好材料时：

> 使用 ruanzhu-kit，在当前已登录的版权中心填写申请表，上传我指定的说明书和源程序 PDF，核对后保存草稿。

命令行初始化示例（将 `<skill目录>` 换为安装路径）：

```bash
python3 <skill目录>/scripts/create_config.py --project-name "我的项目" --output soft-copyright-materials/ruanzhu.config.json
python3 <skill目录>/scripts/manual_spec.py --repo . --out soft-copyright-materials/说明书素材.json
```

补全真实资料和素材后，按 [SKILL.md](SKILL.md) 运行材料生成、检查、PDF 渲染和填表流程。`manual_spec.py`、`generate_docs.py`、版权/AIGC 检查和源码材料提取不要求先启动项目；只有截图、页面核验和页面数据创建才需要运行前后端。用户明确要求截图时，agent 必须用 computer-use / 浏览器工具切换真实模块并调用 `capture.py` 落盘，不能静默生成“截图预留”；只有明确不需要截图的后端/离线材料才跳过运行阶段。项目材料应保存在业务项目目录，不要提交到本工具仓库。

默认说明书使用 10 章基础结构；复杂项目可在项目配置的 `extra_chapters` 中添加真实存在的章节，简单项目不需要凑足固定章数。
说明书页数默认以约 40 页为复核目标（35–45 页为建议范围）。页数由真实内容决定，工具只在偏离范围时提示，不会用空白页或重复段落凑页数；可用 `manual_page_target` / `manual_page_tolerance` 按项目调整。

后端项目可在配置的 `api_examples` 中补充少量经源码核验的核心 REST 接口；生成器会把方法、路径、请求字段、响应字段和状态码写入“核心 REST API 数据结构”附录。未配置或没有可核验接口时不生成该附录，避免把内部路由或猜测内容写进正式材料。

### 截图前准备项目数据

```bash
python3 <skill目录>/scripts/prepare_demo_data.py \
  --repo <项目源码目录> \
  --project-name "软件名称" \
  --spec <材料目录>/说明书素材.json \
  --out <材料目录>/演示数据方案.json
```

该命令只生成方案，不直接写库。后续由 agent 在本地运行的项目中，通过浏览器插件或 Computer Use 按页面流程创建记录；不使用“测试”“示例”“demo”等占位名称，也不写入生产数据库。

需要启动项目时可先执行 `scripts/project_runtime.py inspect`；只有截图/页面核验阶段才使用带 `--allow-run` 的 `start`。接口没有页面入口时，可复制 `assets/demo-data-api.example.json`，先执行 `apply_demo_data.py apply` 预览，再显式添加 `--allow-write`，截图完成后用回滚记录撤销本地数据。材料生成、说明书和源程序处理仍不要求项目运行。

多份软著需要代码级隔离时，使用 `scripts/softcopyright_branch.py create` 创建 `copyright/<名称>` 独立工作树，并用 `check-overlap --repo <项目目录>` 检查 `source_files` 是否重复；脚本不自动 push。

源程序提取前可先生成可视化预览：

```bash
python3 <skill目录>/scripts/source_preview.py \
  --config <材料目录>/ruanzhu.config.json \
  --repo <项目目录> \
  --out <材料目录>/源程序材料预览.html
```

用浏览器打开 HTML 即可查看裁剪前后统计和逐文件脱敏样本；预览不上传源码，也不修改项目文件。

截图整理后可执行 `scripts/screenshots.py --check --fail-on-missing`，确认清单中的图片、说明书模块和后端真实证据已全部覆盖；后端截图建议命名为 `api-docs.png`、`api-success.png`、`api-error.png`、`runtime-log.png`。

### 朱雀检测闸门

```bash
python3 <skill目录>/scripts/zhusque_check.py bind --open
python3 <skill目录>/scripts/zhusque_check.py finalize <材料目录> \
  --allow-upload --report <材料目录>/朱雀检测报告.md
```

桌面 App 生成材料后会主动进入朱雀闸门：配置 Key 时自动调用腾讯官方 `zhuque-text` classify API，完成后才显示“已完成朱雀检测”；未配置时弹出获取 Key 的引导，并提供 [朱雀网页检测](https://matrix.tencent.com/ai-detect/) 手动回退入口。命令行仍需显式运行 `finalize --allow-upload`。朱雀检测是必需闸门：用户明确拒绝时用 `zhusque_check.py decline <材料目录> --user-declined --reason "…"` 记录，累计 2 次独立拒绝才豁免放行，清单和看板会标注“未检测·用户豁免”。第一次绑定会跳转到 [腾讯 EdgeOne Makers API Key 页面](https://console.cloud.tencent.com/edgeone/makers?tab=models&subTab=apikey)。Key 不写入仓库、项目配置或检测报告；相同文本块使用本机缓存，强制重测可加 `--no-cache`。

### 实验性 Jev 材料闸门（暂不纳入默认流程）

Jev 适合做“是否需要人工复核”的结构化分流，不替代本地 AIGC/版权规则，也不替代朱雀报告。看板默认不调用网络；需要时先设置本机环境变量 `TYPESAFE_API_KEY`，再明确确认上传有限摘要：

```bash
python3 <skill目录>/scripts/dashboard.py \
  --config soft-copyright-materials/ruanzhu.config.json \
  --repo <项目目录> --jev --allow-upload
```

默认请求只包含材料名称、端类型、本地检查指标和截图数量，不包含源程序、说明书正文或 API Key。若确认摘要不含机密信息，可对单个材料额外执行 `python3 scripts/jev_check.py <材料目录> --allow-upload --include-excerpt` 发送截断正文；TypeSafe 条款明确提醒不要提交机密或专有材料。结果会缓存到本机缓存目录，默认闸门为：UI/交互 ≥ 0.95、工程达标 ≥ 0.95、需要人工复核 ≤ 0.05；阈值可在配置的 `jev` 节调整。首次使用请在 [TypeSafe 控制台](https://console.typesafe.ai/) 获取 Key；Key 不写入仓库。

## 当前版本的边界

v1.0.4 是基于 2026-09-23 的本地版本；当前工作区仍可能包含未发布的材料边界和环境增强。以下规则和能力限制仍需人工核实：

- 旧文档存在随机选择日期、统一填写未发表的表述；不能作为实际申报依据。日期、发表状态和权利范围应来自真实资料，未知时留待用户补充。
- 来源检查是规则扫描，不能证明代码权属；不能因缺少声明便认定为自研，也不能用清理功能掩盖来源或删除必须保留的许可声明。
- AIGC 分数只反映本地规则中的文风特征，不能识别生成模型，也不保证与外部检测一致。所附样本标签是历史校准记录，不代表本次发布重新验证的准确率。
- 可在终检时使用 `aigc_check.py --max-suspect-ratio 0.20` 限制本地“疑似+AI”结构占比；这只是送朱雀前的本地闸门，不替代朱雀结果。
- 说明书 PDF 采用 A4 纸张、十章基础目录、较宽行距和右下角页码；复杂项目可通过 `extra_chapters` 扩展章节，未自动实现所有小节跳转。
- PDF 默认按“软件简称-端类型+材料类型”命名，例如 `AI 协作-后端源码.pdf`、`AI 协作-桌面端源码.pdf`、`AI 协作-桌面端软件说明.pdf`，并统一放在每份软著目录的 `提交材料/`；端类型可用 `artifact_label` 明确配置，旧版泛化文件名仍可兼容读取。
- 两份软著草稿的浏览器填报经验已整理到 [references/draft-filling-playbook.md](references/draft-filling-playbook.md)，生成材料后可用 `scripts/artifact_manifest.py --verify --strict` 在上传前核对端类型、材料类型、页数、文件哈希和表单路径。
- 每份软著目录中的 `材料上传清单.json` 是正式材料边界；版权/AIGC/朱雀/看板发现它后只扫描清单中的 `提交材料/` 提交件和复核文件，不会把旧版未裁剪材料当成正式产物。
- `source_map`、源码路径和取材层级仅用于内部材料清单与版权检查，不会写入软件说明书正文；说明书正文只保留用户可见功能、操作步骤和真实证据。
- 说明书环境章节优先读取项目 `env` 中的真实硬件/系统/运行支持信息；缺少事实时不会把“实际硬件要求/实际运行环境/实际权限要求”等模板占位句写进正式 PDF。
- 可在配置顶层设置 `reference_materials.root` 指向既有软著材料目录。工具只核对章节组织、版式和可验证事实，并生成 `参考材料核对.md`；参考项目未在当前源码、运行记录或截图中验证的名称和功能不会复制到正式 PDF。
- 自动化无法替代对材料事实的核对；登录、验证码和最终提交由用户操作。

## 开发与发布

### 修复同步规则

生成器、PDF 排版、校验和填表相关问题，必须同步修改 `scripts/`、`tests/` 及对应文档后，再重新生成项目材料。只修改某个项目的 PDF/Markdown 不算完成修复。完整测试通过后，才能把新规则用于当前项目；跨机器同步则需要更新版本并发布 Release。

```bash
python3 -m unittest discover -s tests -v
python3 scripts/oss_selftest.py
python3 scripts/aigc_calibrate.py
python3 scripts/preflight.py --strict
python3 scripts/package_release.py
```

最后一条命令在 `dist/` 生成带版本号的 `.skill`、通用下载名 `.skill` 和 SHA-256 校验文件。维护者更新 `VERSION` / `CHANGELOG.md`，提交后创建同名 `vX.Y.Z` Git 标签，再在 GitHub Release 上传这些产物。安装用户运行更新命令即可拉取后续 main 分支版本。

## 许可证

MIT，见 [LICENSE](LICENSE)。许可证适用于本仓库工具；用户项目和生成材料的权利归属不因使用本工具改变。

## 生成式人工智能合规声明

“人工智能软件”自动生成《关于符合〈生成式人工智能服务管理暂行办法〉声明》的 Word/PDF 模板；其他软件按需开启。默认 `ai_compliance.mode` 为 `auto`，可配置 `always` / `never`；项目配置覆盖全局。也可独立补充：

```bash
python3 scripts/ai_compliance.py --config ruanzhu.config.json --project <项目id> --mode always --pdf
```

编辑稿和生成记录输出在各项目的 `补充声明/`，最终 PDF 输出到同项目的 `提交材料/`；统一使用项目名称、版本、著作权人，签章留空，未提供签署日期则留空，不自动签署或上传。已接入常规生成流程、材料清单与看板。[配置与模板说明](references/ai-compliance.md)。
