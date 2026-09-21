---
name: ruanzhu-kit
description: 软著工具箱。Use when Codex or Claude needs to analyze a software project and generate reusable Chinese software copyright registration materials, including project splitting, naming, application-form copy, software manuals with clickable table of contents, source-code DOCX/PDF extracts, validation records, copyright-risk checks and removal of all repository/open-source traces (GitHub/Gitee URLs, license headers, badges; third-party code auto-excluded), AIGC (AI-generated text) style detection and removal for manuals and application copy, and packaged deliverables based on a configurable workflow. Also covers auto-filling the R11 form on register.ccopyright.com.cn by driving the user's already logged-in Chrome through the browser extension (or computer-use); it stops at saving a draft and never submits.
---

# 软著工具箱

## 每次使用前检查更新（必须执行）

每次用户开始一个使用本 Skill 的新任务时，先执行以下命令，再进入业务流程；同一任务的连续步骤不重复检查。`<skill目录>` 是本次读取的 SKILL.md 所在目录，不是用户业务项目目录。

```bash
python3 <skill目录>/scripts/check_update.py --json
```

- 每次调用都会查询 GitHub 最新正式 Release，没有按日缓存；默认网络超时 4 秒。
- `current` / `local_newer`：直接继续任务，不必打断用户。
- `update_available`：简短告知本地版本、最新版本及发布链接，然后继续当前任务；只有用户要求更新时才运行 `manage_install.py update` 或更换安装包。更新后重新读取 SKILL.md。
- `check_failed`：提示“暂时无法检查更新，继续使用本地版本”，继续任务，不反复重试。
- 检查只读取本地 VERSION 和公开版本元数据，不上传业务项目、申请材料、身份信息，不自动改写安装文件。
- 宿主禁用网络或命令执行时，说明本次未能检查；不得声称已是最新版本。

此步骤由读取本 Skill 的 agent 执行。它不是操作系统后台服务，也不能强制不遵循 SKILL.md 的客户端自动执行。直接调用单个业务脚本时，请先自行运行上述命令。

---

## 黄金原则（必须遵守）

1. **一份代码 = 一份软著（默认）**  
   除非用户明确要求多份，否则一个代码库只产出一份软著材料。

2. **多份软著时，三重隔离缺一不可**
   - 功能不重叠：每份软著覆盖不同业务域，核心功能描述不能互相包含  
   - 源码不重复：每个源文件只能归属一份软著，不得跨软著共享取材  
   - 说明书不相同：每份说明书的功能模块章节描述不同功能，内容不得复制粘贴

3. **名称与功能强相关**  
   软著名称必须直接对应其核心功能模块（例如"广告投放系统"的说明书只讲投放相关功能，不讲素材管理）。

4. **自检问题（拆分后必须都回答 Yes）**  
   - 不看另一份说明书，能独立描述这份软著的核心功能吗？  
   - 这份软著的名称，看到名字就能猜到它主要做什么吗？  
   - 这份软著的源码文件，全部属于它名称对应的功能模块吗？

---

## 完整工作流（9 步）

```
Step 1  分析项目    →  读取代码结构 + instructions 设计文档 + manual_spec.py 抽说明书素材
Step 2  拆分决策    →  确认数量、名称、功能边界、源码分区（与用户确认）
Step 3  生成配置    →  create_config.py  →  ruanzhu.config.json
Step 4  生成材料    →  截图/数据为可选运行阶段；generate_docs.py（按源码/素材生成 + 自动本地 AIGC 初稿处理）+ generate_source_docx.py
Step 5  版权清除    →  预检 → 提取时跳过第三方、清除自有开源痕迹 → oss_scrub.py 清说明书 → 闸门（材料零开源痕迹）
Step 6  AIGC 去痕  →  aigc_check.py 检测 → aigc_rewrite.py 清理 + 任务单 → 改写 → 复测 < 35
Step 7  转 PDF     →  render_pdfs.py  →  说明书.pdf + 源程序鉴别材料-60页.pdf（再跑一次 Step 5/6 终检）
Step 8  填写表单    →  application_form.py 汇总字段 → form_plan.py 出操作计划 → 浏览器插件填表存草稿
Step 9  人工确认    →  浏览器核对 → 手动点「确认填报」提交

任何时候想看整体进度：`python3 scripts/dashboard.py --config <配置> --repo <项目目录>`
→ 生成 `<output_root>/看板.html`，一页显示有几份软著、各自缺什么材料、AIGC 与版权风险、以及每条待办对应的命令。
```

---

## Step 1 — 分析项目

### 1.1 读取顺序

按优先级依次读取：

1. `instructions/` 目录（如存在）：系统总体设计、功能模块设计、数据库设计、接口设计、部署运维指南
2. `README.md` / `README_CN.md`
3. `package.json` / `pom.xml` / `build.gradle`（了解技术栈）
4. 主要模块目录结构（`src/`、`app/`、`lib/`、`modules/`等）
5. 入口文件和核心 Service/Controller 文件

### 1.2 抽取说明书素材（说明书质量的决定因素）

说明书写不好，基本都是因为落笔时手上只有模块名。先把界面上真实存在的东西挖出来：

```bash
python3 scripts/manual_spec.py --repo <项目目录> \
  --out soft-copyright-materials/说明书素材.json --max-pages 25
```

产出 `说明书素材.json` 和 `说明书素材预览.md`，每个页面含：模块名（取自界面标题文字）、进入位置（路由/目录）、
界面控件文字、取值约束、提示语、错误码、源码文件与行数；同时统计全项目源码行数（申请表“源程序量”用它）。

如果扫描到后端接口，素材 JSON 还会给出 `backend`、`apis` 和 `evidence_plan`。接口路径、方法、文件和行号只从源码抽取；抽不到的事实不补写。后端说明书的证据计划默认包含三类必需真实材料：成功响应、参数校验/4xx 错误响应、启动或业务日志；只有检测到项目实际启用 Knife4j/OpenAPI 时，调试页才会标为必需。

**必须先与用户确认预览表**：模块名和进入位置是否与真实界面一致，哪些页面不该写进说明书，
再补 `purpose`（这个界面解决什么）、`steps`（操作顺序）、`scope_note`（不负责的范围）三个字段。
脚本只抽取不编造，抽不到的字段留空——空着就得读源码补，不能凭空写。

### 1.3 提取关键信息

| 信息 | 来源 |
| --- | --- |
| 软件整体定位 | README / 系统总体设计 |
| 核心功能模块列表 | 功能模块设计 / src 目录 |
| 技术栈 | package.json / pom.xml / README |
| 源码文件清单 | 目录结构扫描 |
| 著作权人 | 用户确认 / 登录账户 |

### 1.4 instructions 目录规范（输入标准）

如果项目存在 `instructions/` 目录，优先读取以下文件作为说明书生成的输入：

```
instructions/
├── 01-系统总体设计.md      ← 系统定位、架构图、技术选型
├── 02-功能模块设计.md      ← 各模块功能详细描述
├── 03-数据库设计.md        ← 核心数据表和字段（可选）
├── 04-接口设计.md          ← 核心接口清单（可选）
└── 05-部署运维指南.md      ← 环境要求、部署步骤、运维说明
```

如果不存在，Claude 根据代码结构自行推导，但应先与用户确认关键模块清单再生成。

---

## Step 2 — 拆分决策与隔离方案

### 2.1 默认：不拆分

**一份代码库 → 一份软著。** 只有在满足以下全部条件时才考虑拆分：

| 条件 | 说明 |
| --- | --- |
| ≥ 2个独立业务域 | 功能模块之间业务无强依赖，各自可单独使用 |
| 每个拆分单元 ≥ 2000 行独立源码 | 各部分有足够代码支撑 60 页源程序材料 |
| 用户有明确多份软著需求 | 拆分不是为了凑数，而是有真实注册需求 |

### 2.2 拆分边界划定方法

**按业务域划分（推荐）：**

```
示例：ShopAny 广告系统（可拆为 3 份）
├── ShopAny 智能广告投放系统   ← 广告创建/投放/状态管理相关代码
├── ShopAny 广告素材管理系统   ← 素材上传/审核/检索相关代码
└── ShopAny 广告数据报表系统   ← 报表统计/数据查询/BI相关代码
```

**划定边界的三步法：**

1. 列出所有功能模块，按"是否服务于同一用户目标"归类
2. 为每组模块起一个产品化名称（像真实软件产品一样）
3. 将源码文件逐一分配到各组（每个文件只属于一组）

### 2.3 源码分区规则

```
规则 1：每个源文件归属且仅归属一份软著
规则 2：公共工具类（util/common/helper）归属功能最相关的那份，或均摊（行数最多者优先）
规则 3：数据库 DO/Entity 按其服务的业务模块分配
规则 4：Controller 跟随 Service 归属
规则 5：各份软著取材行数应尽量不同（建议相差 ≥ 200 行，避免高度相似）
```

多份材料需要代码级调整时，先创建独立软著分支和工作树，主分支保持不动；
脚本不会自动推送远程，也不会自动覆盖已有目录：

```bash
python3 scripts/softcopyright_branch.py create --repo <项目目录> \
  --name ai-collab-backend --base main
python3 scripts/softcopyright_branch.py create --repo <项目目录> \
  --name ai-collab-backend --base main --apply
python3 scripts/softcopyright_branch.py check-overlap \
  --config soft-copyright-materials/ruanzhu.config.json --repo <项目目录> --fail-on-overlap
```

第一条只预览，第二条才创建 `copyright/<名称>` 分支及仓库外独立工作树。
`check-overlap` 用于提前发现多份软著共用同一源码文件或配置中列出的文件不存在，
不能替代人工确认功能边界，也不会通过改名掩盖真实来源。

### 2.4 确认清单（与用户确认后再继续）

生成材料前，向用户展示并确认：

```
软著数量：X 份

软著 1：[名称]
  核心功能：[2-3 句话描述]
  源码范围：[主要目录/文件]
  预计行数：约 XXXX 行

软著 2：[名称]
  核心功能：[2-3 句话描述]
  源码范围：[主要目录/文件]
  预计行数：约 XXXX 行
```

---

## Step 3 — 生成配置

```bash
python3 scripts/create_config.py --project-name "MyProject" \
  --output soft-copyright-materials/ruanzhu.config.json
```

`ruanzhu.config.json` 关键字段：

| 字段 | 说明 |
| --- | --- |
| `copyright_holder` | 著作权人全称 |
| `development_completed_date` | 开发完成日期（各份软著可不同，选上周随机工作日） |
| `projects[].name` | 软件全称（与其核心功能强相关） |
| `projects[].source_files` | 该软著专属源文件列表（不与其他软著共享） |
| `projects[].modules` | 功能模块 `[["模块名", "说明"]]`（只写本软著的功能） |
| `projects[].extra_chapters` | 复杂项目的扩展章节；默认空数组，按实际功能增加 |

---

## Step 4 — 生成材料

`manual_spec.py`、`generate_docs.py`、版权检查、AIGC 检查、源码材料提取和 PDF 生成均可在**不启动前端/后端项目**的情况下完成，输入是源码、配置和已有素材。只有浏览器/模拟器截图、页面实际操作核验、准备页面演示数据和运行时错误验证才需要启动项目。

```bash
# 可选：需要真实界面截图时才启动项目；不需要截图可直接从 generate_docs.py 开始
# Web 项目先自动拍，再整理编号（非 Web 项目跳过 capture.py，人工截图放进 用户截图/）
python3 scripts/capture.py --base-url http://localhost:5173 \
  --spec soft-copyright-materials/说明书素材.json \
  --out soft-copyright-materials/01-XXX软件/用户截图
python3 scripts/screenshots.py --materials soft-copyright-materials/01-XXX软件 \
  --spec soft-copyright-materials/说明书素材.json

python3 scripts/generate_docs.py \
  --config soft-copyright-materials/ruanzhu.config.json

# 提取源程序前，先做版权预检并配置 self_open_source / self_aliases（见 Step 5）
python3 scripts/copyright_check.py --config soft-copyright-materials/ruanzhu.config.json \
  --repo . --skip materials

python3 scripts/generate_source_docx.py \
  --config soft-copyright-materials/ruanzhu.config.json --repo .

# 先预览裁剪效果（不会生成 DOCX，不会改源代码）
python3 scripts/source_preview.py \
  --config soft-copyright-materials/ruanzhu.config.json --repo . \
  --out soft-copyright-materials/源程序材料预览.html

# 生成 DOCX 的同时输出预览
python3 scripts/generate_source_docx.py \
  --config soft-copyright-materials/ruanzhu.config.json --repo . --preview
```

`generate_source_docx.py` 默认：跳过第三方文件；清除自有代码的许可证头、仓库地址和开源注释（`"scrub_open_source"`）；脱敏密钥、手机号、邮箱、内网 IP（`"redact"`）；为避免源程序鉴别材料被导入块和注释挤占，默认只在输出材料中裁剪普通注释、`import/include/use` 声明和连续空行。原项目源文件不会被改写。

每个 `projects[]` 可用 `source_material` 调整裁剪策略：

```json
"source_material": {
  "trim_comments": true,
  "trim_imports": true,
  "max_blank_lines": 1
}
```

命令行可临时使用 `--keep-comments` 或 `--keep-imports` 保留对应内容。Go 的 `import (...)`、Python/JavaScript 的多行导入、C/C++ 的 `#include` 等会整体移除；包声明、函数签名和业务实现保留。

`源程序材料预览.html` 是本地单文件页面：顶部显示原始/裁剪后行数、移除注释数、移除导入数、跳过第三方文件数和预计页数；下方按文件列出状态，并可展开查看脱敏后的裁剪样本。预览默认不展示被判定为第三方的文件正文。

每份软著生成：

1. `软件说明书.md`（Step 7 渲染为 PDF）
2. `申请表填报文案.md`
3. `源码材料清单.md`
4. `源程序提取/源程序鉴别材料-XX页.docx`

### 4.0 真实演示数据准备（截图前）

软著说明书不能只放“测试数据”“示例名称”这类占位内容。需要截图或演示数据时，先从项目源码字段、枚举、页面素材和软件名称生成一份与项目语义一致的合成数据方案：

```bash
python3 scripts/prepare_demo_data.py \
  --repo . \
  --project-name "XXX软件" \
  --spec soft-copyright-materials/说明书素材.json \
  --out soft-copyright-materials/演示数据方案.json
```

脚本只扫描和生成方案，不连接数据库、不写远程服务；会跳过密码、Token、密钥、手机号、身份证和账号等敏感字段，并拒绝“测试 / test / demo / mock / 示例”等占位词。方案同时生成 `演示数据方案.md`，列出记录值、页面入口、需要填写的字段和回滚要求。数据准备是可选运行阶段，不影响离线材料生成。

启动项目后，agent 按方案优先使用项目本地页面，通过浏览器插件或 Computer Use 创建记录；页面没有创建入口时，再使用项目提供的本地 API。每条记录要保存接口返回的业务编号，截图结束后可以按编号回滚。禁止直接连接生产数据库，也不能把方案里的合成记录当作真实业务事实写进说明书。

只有数据创建并在页面上核对成功后，才进入下面的截图步骤。

#### 4.0.1 可选的本地运行与 API 数据执行

材料生成本身不需要启动项目。需要页面截图或页面核验时，先只分析可用启动命令：

```bash
python3 scripts/project_runtime.py inspect --repo <项目目录>
python3 scripts/project_runtime.py start --repo <项目目录> --allow-run
python3 scripts/project_runtime.py status --repo <项目目录>
python3 scripts/project_runtime.py health http://127.0.0.1:5173/health
python3 scripts/project_runtime.py stop --repo <项目目录>
```

`start` 只允许显式启动本地进程，日志和会话信息放在项目 `.ruanzhu/runtime/`；
不传 `--allow-run` 时不会启动。浏览器插件或 Computer Use 仍是页面操作和截图的首选。

页面没有合适的创建入口时，才配置本地 API 适配器（可复制
`assets/demo-data-api.example.json`）。执行默认是预览，不会写库：

```bash
python3 scripts/apply_demo_data.py apply \
  --plan <材料目录>/演示数据方案.json \
  --config <材料目录>/演示数据接口.json
python3 scripts/apply_demo_data.py apply \
  --plan <材料目录>/演示数据方案.json \
  --config <材料目录>/演示数据接口.json --allow-write
python3 scripts/apply_demo_data.py rollback \
  --rollback-file <材料目录>/演示数据回滚.json \
  --config <材料目录>/演示数据接口.json --allow-write
```

写入默认只允许 `localhost` / `127.0.0.1` / `::1`，必须显式配置接口、显式加
`--allow-write`；脚本按接口返回的业务 ID 生成逆序回滚记录，不保存授权头，不连接数据库。

### 4.1 说明书素材与截图

`generate_docs.py` 检测到 `说明书素材.json` 后，功能模块章节按每个页面生成四小节：
（一）功能说明 /（二）界面与入口（进入位置、界面元素、取值约束、操作反馈）/（三）操作步骤 /（四）异常处理（错误码表）。
界面元素、提示语、错误码直接来自源码，Claude 只需补操作顺序和处理方法，改写量比空模板小得多。

截图三种来源，都归到 `截图清单.json`：

先探测本机可用的截图端：

```bash
python3 scripts/capture.py --detect
```

| `--target` | 适用 | 依赖 | 方式 |
| --- | --- | --- | --- |
| `web` | Web/H5/管理后台/H5 游戏 | Chrome（已有） | 按素材里的路由**批量**截；HTTP ≥400 跳过，纯色图自动删 |
| `ios` | iPhone/iPad 模拟器 | Xcode | `simctl` 截当前屏幕 |
| `ios-device` | USB 连接的 iPhone 真机（iOS 16 及以下） | libimobiledevice | `idevicescreenshot`；iOS 17+ 会提示需挂开发者镜像，改用下一行 |
| `ios-mirror` | iPhone 真机（iOS 17+ 推荐） | QuickTime | **用户本人**先在 QuickTime「新建影片录制」里把来源选成 iPhone，脚本只截这个窗口——不会自动新建录制，避免误开 Mac 摄像头拍到人 |
| `android` | 安卓模拟器或 USB 真机 | adb | `adb screencap` |
| `mac` | 任意 macOS 应用窗口（桌面应用、Electron） | 系统自带 | 按应用名定位窗口后 `screencapture` |
| `miniprogram` | 微信小程序 | 微信开发者工具 | 截开发者工具模拟器窗口（mac 通道快捷方式） |
| `auto` | — | — | 自动挑一个可用的端 |

web 是批量的；其余一次截一张当前屏幕——由人或 agent（computer-use / iOS 模拟器工具 / adb 输入）
先把界面点到位，再调用脚本落盘：

```bash
python3 scripts/capture.py --target ios --name 神将招募 --out <材料目录>/用户截图
python3 scripts/capture.py --target mac --app 微信开发者工具 --name 房源列表 --out <材料目录>/用户截图
```

| 场景 | 做法 |
| --- | --- |
| 需要登录的网页 | `capture.py --login --profile <目录>` 开有界面的 Chrome，**用户本人登录一次**，之后复用该会话；agent 不碰账号密码 |
| 用户自己截 | 放进 `<材料目录>/用户截图/`，文件名带模块名（如 `1_神将招募.png`）便于自动对号 |
| 不放截图 | 说明书保留“【截图预留：模块名】”，审查时一眼看出缺哪张 |

注意：`mac` / `miniprogram` 需要 macOS 的**屏幕录制**权限（系统设置 › 隐私与安全性 › 屏幕录制，
勾选运行脚本的程序后重启它），否则截出来是纯黑图——脚本会检测到纯色图并报错，不会把黑图混进说明书。
前端路由项目若素材里的 entry 不是真实 URL，用 `--routes /login /house/list` 手工指定。

`screenshots.py` 只整理、编号、对号，不生成图片；对不上模块的截图会提示，改文件名或手工改清单的 `module` 字段即可。截图前必须优先使用 4.0 生成并创建项目相关数据，禁止用“测试用户”“示例订单”等无业务含义文本代替。

整理完成后可单独校验材料完整性（不启动浏览器、不生成图片）：

```bash
python3 scripts/screenshots.py --materials <材料目录> --spec <材料目录>/说明书素材.json \
  --check --fail-on-missing
```

它会检查清单文件、图片路径、空文件、未匹配截图和缺少截图的功能模块。

后端项目把截图文件名写成 `api-docs.png`、`api-success.png`、`api-error.png`、`runtime-log.png`（也支持 `knife4j`、`swagger`、`日志` 等关键词），脚本会写入 `evidence_id` 并在 `--check --fail-on-missing` 时校验必需证据。没有真实运行结果时保留“待截图”，不要制作伪造页面或伪造 JSON。

### 4.2 说明书文风要求（必读）

脚本生成的是模板骨架。**产出终稿前，必须按 [references/writing-style.md](references/writing-style.md) 的规范人工充实并改写全部散文章节**，要点：

- **功能按“（一）功能说明 /（二）操作步骤 /（三）异常处理”写**：步骤带界面真实文字、取值约束、失败分支——朱雀实测唯一稳定判人工的写法（0.16），`generate_docs.py` 已按此生成骨架
- 结构禁忌：密集括号补注、“**X**：”粗体排比、“**Qn：**”FAQ 连排、分号收尾的列表（实测 0.78–0.999 判 AI，即使事实很多）
- 黑名单句式（“覆盖…体系”“提供…能力”“沉淀为”“核心意义在于”“无论是…还是…都”等）清零
- 删除“系统优势/技术优势/功能优势/应用优势/核心价值”等通用总结标题；“整套业务闭环是完整的”等结论句改成真实入口、处理、结果和失败分支
- 关注“可以/系统/模块”等高频词。`aigc_check.py` 会输出全文次数和每千字频率；处理重复主语和模板段落，不做没有语义依据的同义词替换
- 每段至少一个真实事实（界面文字/路径/版本号/错误码）——为了真实，不指望它降分；**禁止编造**
- 表格为可读性服务，不当降分手段（实测 0.24–0.997 不稳定）；正式书面语即可，不必刻意口语化
- 写完后在 Step 6 用 `aigc_check.py` 量化验证，不靠自我感觉

### 4.3 说明书隔离要求

| 章节 | 隔离要求 |
| --- | --- |
| 软件概述 | 定位描述只涉及本软著核心功能，不提其他软著的功能 |
| 功能模块 | 所有功能点必须在本软著的功能边界内 |
| 技术特点 | 技术亮点要与本软著的核心功能挂钩 |
| 接口清单 | 只列本软著相关的接口（如有） |

### 4.4 多份软著说明书页数建议

| 份数 | 页数建议 |
| --- | --- |
| 1 份 | 不限（通常 50-80 页） |
| 2 份 | 分别生成，页数相差 ≥ 10 页 |
| 3 份 | 建议 60、62、64 页（或其他明显差异组合） |

---

## Step 5 — 版权风险检查与开源痕迹清除

**硬性要求：申报材料中一律不得出现 ① 开源协议 ② 仓库/托管地址 ③ 引用来源。** 很多项目是先开源、后上架再申请软著，这些痕迹要在生成材料时清除。Star 评分、Issue 工单、fork、PR、贡献者、社区、GitHub 登录等业务用语不在清除范围。细则见 [references/copyright-risk.md](references/copyright-risk.md)。

先在 `ruanzhu.config.json` 中配置：

```json
"first_publication_date": "未发表",
"self_open_source": true,
"self_aliases": ["GitHub/Gitee 账号或组织名", "LICENSE 里的英文名/团队名"]
```

```bash
S=scripts; C=soft-copyright-materials/ruanzhu.config.json; R=<上架版本源码目录>
python3 $S/copyright_check.py --config $C --repo $R --skip materials   # ① 预检
python3 $S/generate_source_docx.py --config $C --repo $R                # ② 提取：跳过第三方 + 清除自有痕迹 + 脱敏
python3 $S/oss_scrub.py --config $C                                     # ③ 说明书/申请表：预览
python3 $S/oss_scrub.py --config $C --apply                             #    写回（留 .bak）
python3 $S/copyright_check.py --config $C --repo $R --fail-on high      # ④ 闸门
```

| 代码 / 文本 | 处理 |
| --- | --- |
| 自有代码（版权人是著作权人或 `self_aliases`） | 提取时自动删除：文件头许可证/版权块、含协议文本或引用标记（参考自/摘自/forked from…）的注释行、仓库/徽章/博客地址、`git clone` 类命令；源程序材料默认再裁剪普通注释和导入/include/use 声明，原代码不改 |
| 第三方代码（他人版权声明、`node_modules`/`vendor`/`dist`、压缩代码、开源脚手架） | 提取时自动跳过，整份不进材料；不删他人声明。跳过后行数不足会报警，需补选自研文件 |
| 说明书 / 申请表 / auto-fill 文案 | `oss_scrub.py` 删除“开源协议/License/致谢/参考资料/Star History”整节、徽章行，以及含协议名、开源声明（已开源/源码托管在 Gitee…）、引用标记、开源项目名、仓库或博客地址的句子和表格行 |
| 产出层复查 | 任何协议、地址、引用残留都判高风险，闸门不通过 |
| 规则回归 | 改规则后跑 `python3 scripts/oss_selftest.py`（业务词保留 / 开源痕迹删除共 50 例） |

纪律：

- **发表状态一律按“未发表”**：申报的是上架版本，与开源参考代码有本质区别；源程序必须取自上架版本。
- 第三方代码不删声明、不改写冒充自研，只换文件；项目基于他人开源脚手架时，先向用户说明，只申报自研部分。
- 清除后段落变短、读起来断的，在 Step 6 按操作动线补写。
- 高风险清零才能进入 Step 7；只能发现留下痕迹的第三方代码，来源存疑的大项目再用 scancode-toolkit 等工具排查。

---

## Step 6 — AIGC 检测与去除

脚本生成的骨架和 AI 起草的正文都带明显模板痕迹。**渲染 PDF 之前必须过这一步**，细则见 [references/aigc-detection.md](references/aigc-detection.md)。

```bash
M=soft-copyright-materials/01-XXX软件      # 多份软著时逐个目录执行
S=<skill目录>/scripts

python3 $S/aigc_check.py $M --report $M/AIGC检测报告.md    # ① 检测
python3 $S/aigc_rewrite.py $M                              # ② 预览机械清理 diff
python3 $S/aigc_rewrite.py $M --apply                      #    确认后写回（留 .bak）
#   ③ Claude 按 $M/AIGC改写任务单.md 逐条改写 .md（先查源码，再动笔）
python3 $S/aigc_check.py $M --report $M/AIGC检测报告.md --fail-above 35   # ④ 闸门
# 如需更严格控制本地疑似+AI结构占比：追加 --max-suspect-ratio 0.20
```

| 环节 | 谁做 | 要点 |
| --- | --- | --- |
| 检测 | `aigc_check.py` | 本地离线，支持 .md / .txt / .docx / .pdf / `auto-fill/config.json`；按章节打分，给出朱雀同口径的人工/疑似/AI 字数占比和高风险块原因 |
| 机械清理 | `aigc_rewrite.py` | 删营销词、套话、“进行X”，列表分号收尾→句号，去列表粗体引导；代码块不动 |
| 语义改写 | Claude | 按任务单逐条改，任务单已按问题附改法和示范；优先把能力描述改成操作步骤+失败分支；**查不到的事实就删空话，禁止编造** |
| 闸门 | `aigc_check.py --fail-above 35` | 任一文件 >35 分或残留占位符 → 退出码 1，不得进入 Step 7 |
| 终检 | `aigc_check.py 软件说明书.pdf` | Step 7 渲染后对 PDF 再测一次，送检/提交的是 PDF 文本 |
| 校准 | `aigc_calibrate.py` | 改规则后必跑回归（当前 24 段朱雀样本，准确率 88%）；拿到新的朱雀报告用 `--import-report` 导入 |

规则：

- 目标分数：每个文件 < 35（低档），且占位符为 0。一般 2 轮可达；第 3 轮仍不达标，缩短该章节或转表格，不要硬凑。
- 只改 `.md` 源文件，docx/pdf 一律重新生成；多份软著改写时不得引入别家的功能或源码（黄金原则 2）。
- 改完向用户汇报：各文件改写前后分数、改写条数、仍需人工确认的段落。
- 本地分数是按朱雀样本校准的启发式估计，不等于商业检测结论。用户想用外部 AIGC 检测网站复核时，上传材料前须征得用户同意（或让用户自行上传），并先确认已脱敏；结果回来后用 `aigc_calibrate.py --import-report` 回灌样本。

首次生成的默认内容只会引用 `ruanzhu.config.json` 和源码素材；硬件、权限、日志、安装命令、测试结果等字段缺失时输出“待核验”，不会生成看似真实但未经验证的事实。后端项目还会生成 `截图证据计划.md`，要求把真实调试结果补齐后再进入终检。

### 6.1 可选朱雀风格联网检测

需要把材料文本发送给 EdgeOne Makers 的用户，可以显式使用 `scripts/zhusque_check.py`。它兼容 OpenAI Chat Completions 接口，默认模型为 `@makers/deepseek-v4-flash`；这不是本地离线规则的替代品，也不等同于官方商业检测结论。

本地 AIGC 处理会在首次执行 `generate_docs.py` 后自动触发：先运行 `aigc_rewrite.py --apply` 做机械清理，再生成 `AIGC改写任务单.md` 和本地 `AIGC检测报告.md`。这一步完全离线，不会上传材料；任务单中的事实性内容仍需人工/Claude 根据源码确认，不能靠机械替换伪造“人工”文本。

朱雀 API 不会在每次生成或每次改字时自动触发。正文完成事实核对后，使用一次 `finalize` 做全量联网检测；只有用户主动执行并带上 `--allow-upload` 才会上传。最终文本指纹会记录在材料目录内，文本未变化时重复执行不会再次请求。

首次使用时不要把 Key 写进命令、配置或仓库：

```bash
python3 <skill目录>/scripts/zhusque_check.py bind --open
```

命令会提示用户前往 [腾讯 EdgeOne Makers 控制台](https://console.cloud.tencent.com/edgeone/makers?tab=models&subTab=apikey) 自行生成 Key，再交互式绑定到本机 macOS Keychain。也可以临时使用环境变量 `MAKERS_MODELS_KEY`，工具不会打印或写出它。

联网检测必须显式确认上传：

```bash
python3 <skill目录>/scripts/zhusque_check.py finalize <材料目录> \
  --allow-upload --report <材料目录>/朱雀检测报告.md
```

`finalize` 会扫描该材料目录中应检测的全部 Markdown、PDF、DOCX 和填表配置，按唯一文本块执行一次全量检测。没有 Key 时只提示控制台链接并停止；`status` 只显示绑定来源，`unbind` 只删除本机 Keychain 项。检测报告不保存 Key；调用前应确认材料已脱敏，且用户同意将文本发送到外部接口。

截图证据计划、源码材料清单、AIGC/版权内部报告不会作为正文上传；重复正文块仍按本地指纹合并，避免为同一内容重复消耗额度。

为减少重复请求和额度消耗，工具会按规范化文本块做本地指纹去重，并把结果缓存到用户缓存目录（macOS 默认 `~/Library/Caches/ruanzhu-kit/zhusque`，不保存原文和 Key）。同一份材料再次检测、同一文本同时出现在 Markdown/PDF 中时，会优先复用缓存；需要强制重测时加 `--no-cache`。默认每个请求最多 12,000 字符，可用 `--max-chars` 调整。普通 `check` 适合抽查，正文确认后的正式流程使用 `finalize`。

---

## Step 7 — 转 PDF

```bash
python3 scripts/render_pdfs.py \
  --config soft-copyright-materials/ruanzhu.config.json
```

生成：
- `软件说明书.pdf`（含可点击目录）
- `源程序提取/源程序鉴别材料-XX页.pdf`

脚本会校验实际页数，如不符会报警。

---

## Step 8 — 自动填写 R11 表单

### 安装依赖（一次性）

```bash
cd <材料目录>/auto-fill
npm install playwright
npx playwright install chromium
```

### 8.1 字段集中整理（先做这一步）

```bash
python3 scripts/application_form.py --config soft-copyright-materials/ruanzhu.config.json --strict
```

申请表字段一处生成、三处一致：`auto-fill/config.json`（脚本用）、`申请表填报文案.md`（人工对照官网填）、校验清单。

| 字段 | 来源 |
| --- | --- |
| 软件全称/简称/版本/分类 | `ruanzhu.config.json` 的 `projects[]` |
| 著作权人/开发完成日期/发表状态 | 配置顶层；发表状态固定“未发表” |
| 源程序量 | `说明书素材.json` 的全项目源码行数（不是取材行数） |
| 编程语言 | 素材里的 by_ext 行数统计，按行数排序 |
| 开发/运行环境 | 配置里的 `env` 字段；缺了写占位并在校验里报出来 |
| 软件主要功能 | 说明书“功能模块”章节按模块拼 500–1300 字初稿 |
| 两份 PDF | 材料目录里实际存在的文件，路径自动填 |

校验项：占位符、各字段长度上限、主要功能 500–1300 字、日期格式、PDF 是否存在、软件全称与说明书是否一致、源程序量与素材是否一致。拿不到的字段写【待填写】，绝不编。

### 8.2 表单数据结构（auto-fill/config.json，由上一步生成）

```json
{
  "step2_basic": {
    "softwareName": "软件全称（与说明书保持完全一致）",
    "shortName": "简称（10字以内）",
    "version": "V1.0",
    "completionDate": "2026-06-17",
    "published": false
  },
  "step3_dev": {
    "devHardware": "Apple Mac计算机，CPU 8核及以上，内存16GB及以上，磁盘50GB及以上",
    "runHardware": "PC或Mac计算机，内存8GB及以上，具备足够磁盘空间用于软件安装及数据存储",
    "devOS": "macOS 13及以上（Ventura/Sonoma）",
    "devTools": "【开发工具，50字内，例：Electron、React、Vite、Node.js、TypeScript、SQLite】",
    "runOS": "Windows 10/11、macOS系统",
    "runSupport": "【运行支撑环境，50字内，例：Node.js 18.0及以上，Electron 28.0及以上】",
    "language": "JavaScript",
    "languageOther": "TypeScript、TSX、CSS",
    "sourceLines": "【源程序行数】"
  },
  "step4_features": {
    "devPurpose": "【开发目的，50字以内】",
    "targetIndustry": "【面向领域/行业，50字以内】",
    "mainFunction": "【软件主要功能，500-1300字，只描述本软著的核心功能】",
    "techFeatureTag": "人工智能软件",
    "techFeatureText": "【技术特点关键词，100字以内】",
    "programPdf": "../源程序提取/源程序鉴别材料-60页.pdf",
    "docPdf": "../软件说明书.pdf"
  }
}
```

### 字段长度限制

| 字段 | 限制 |
| --- | --- |
| softwareName | 无硬性限制，建议 ≤ 30 字 |
| shortName | ≤ 15 字 |
| devTools | ≤ 50 字 |
| devPurpose | ≤ 50 字 |
| targetIndustry | ≤ 50 字 |
| techFeatureText | ≤ 100 字 |
| mainFunction | 500–1300 字（不足 500 字系统会拒绝） |

`config.json` 由 `application_form.py` 生成，不要手工改；要改内容就改 `ruanzhu.config.json` 再重跑。

填完后，对长文本字段也跑一遍检测（`mainFunction` 是审查员最先看到的文字）：

```bash
python3 <skill目录>/scripts/aigc_check.py <材料目录>/auto-fill/config.json --fail-above 35
```

### 8.3 生成操作计划

```bash
python3 scripts/form_plan.py --config <材料目录>/auto-fill/config.json \
  --out <材料目录>/填表操作计划.md
```

逐控件列出「填什么值 / 长度是否超限 / 填完是否要回读」，主要功能这类长文本单独写到 `auto-fill/长文本/*.txt`，粘贴用。

### 8.4 用浏览器插件填表（默认方式）

**Claude 通过 Claude in Chrome 插件操作用户已登录的 Chrome**（没有插件时用 computer-use 控制桌面 Chrome），
不用 Playwright、不开无头浏览器。细则见 [references/form-filling.md](references/form-filling.md)，要点：

- **登录由用户本人完成**，agent 不碰账号密码和验证码；页面跳登录就把浏览器交回用户。
- 先 `read_page` 按 label 定位控件再填，不靠坐标乱点；Vue 表单填完要失焦。
- 长文本整段粘贴，**填完回读字数**确认没被截断；两份 PDF 用文件上传工具按绝对路径上传。
- 每步填完回读关键字段再点「下一步」。

### 8.5 回读核对（必做）

在确认信息页把页面实际值记成 JSON，交给脚本比对：

```bash
python3 scripts/form_plan.py --config <材料目录>/auto-fill/config.json --verify 回读.json
```

普通字段比文本、长文本比字数（防截断）、PDF 比文件名；标了“填完回读”的字段漏记会判为未核对。
**有不一致先改，不要保存草稿。**

### 8.6 保存草稿 → 交回用户

核对一致后点「保存至草稿箱」，然后告诉用户填了什么、传了哪两个 PDF。
**agent 不得点击「确认填报」「提交申请」**——正式提交由用户本人操作，浏览器保持打开。

备选：`scripts/auto-fill/auto-fill.js`（Playwright 脚本，需 npm 安装）适合页面稳定时批量重复填报，同样只存草稿不提交。

## Step 9 — 人工确认提交

草稿保存后，在浏览器确认信息页检查所有字段，确认无误后**手动点击「确认填报」**正式提交。

---

## 总览看板

材料一多就看不清进度，用看板：

```bash
python3 scripts/dashboard.py --config soft-copyright-materials/ruanzhu.config.json --repo <项目目录>
```

实时调用 aigc_check / copyright_check 扫描，产出单文件 `看板.html`（无外链，双击可看）：

| 区块 | 内容 |
| --- | --- |
| 顶部 | 几份软著、几份可进入提交、版权高危总数、说明书总页数、截图数 |
| 每份卡片 | 名称/版本/著作权人/开发完成日期、说明书字数与页数、源程序页数、AIGC 分数与人工/疑似/AI 占比 |
| 下一步 | 按高/中/低排序的待办，每条附可直接执行的命令 |
| 材料清单 | 六类材料的生成状态与路径 |
| 问题明细 | AIGC 高风险块 + 版权风险，标注位置和改法 |

“可进入提交”的判定：没有高危待办（占位符已填、AIGC < 55、版权无高危、源程序 ≥ 60 页）。
加 `--json` 可同时输出结构化结果，便于比对多轮进度。

---

## 标准产物清单

每份软著输出（存放在各自目录下）：

1. `软件说明书.md`（正文来源）
2. `软件说明书.pdf`（提交件，默认采用参考样式的编号目录、章节编号和右下角页码；无页头、无“第 X 页 / 共 N 页”；由 md 渲染，不经 docx）
3. `申请表填报文案.md`（application_form.py 生成，与填表配置同源）
4. `源码材料清单.md`
5. `截图清单.json` + `截图/`（有截图时）
6. `截图证据计划.md`（后端/API 项目；真实接口、错误响应、日志和调试页采集清单）
7. `演示数据方案.json` + `演示数据方案.md`（截图前创建本地业务数据的方案与回滚提示）
8. `源程序材料预览.html`（源程序裁剪预览，内部留档）
9. `源程序提取/源程序DOCX生成报告.md`（含跳过的第三方文件、脱敏与清除统计）
10. `源程序提取/源程序鉴别材料-XX页.docx`（编辑稿）
11. `源程序提取/源程序鉴别材料-XX页.pdf`（提交件）
12. `auto-fill/config.json` + `auto-fill/长文本/`（填表用）
13. `填表操作计划.md`（form_plan.py 生成）
14. `AIGC检测报告.md`（内部留档，不提交）
15. `AIGC改写任务单.md`（内部留档，不提交）
16. `版权风险检查报告.md`（位于 output_root，内部留档，不提交）
17. `看板.html`（位于 output_root，总览用，不提交）
18. `说明书素材.json` + `预览.md`（位于 output_root，内部留档）

---

## 说明书章节标准（默认 10 章，可按场景扩展）

0. 默认采用 10 章基础结构；复杂项目可在 `projects[].extra_chapters` 中追加数据治理、接口管理、权限审计、任务调度、算法流程等真实章节，简单项目不必为了凑章数扩写。说明书 PDF 默认采用参考样式：简洁编号目录、`01-章节名` 章节标签、软件名与章节名副标题、右下角单页码；目录和正文标题不添加装饰性圆点，不添加页头和“共 N 页”页脚。可通过 `render_pdfs.py --style clean` 切换为底部居中页码的简洁样式（render_pdfs.py 自动处理）
1. 软件概述（定位、目标、特性、适用角色、源码范围；申请人信息和发表信息不写入说明书）
2. 软件架构（架构图、分层说明、技术选型）
3. 环境要求（开发环境、运行环境、第三方依赖）
4. 安装部署（依赖安装、启动方式、构建发布）
5. 配置说明（核心配置项、配置文件、参数说明）
6. 使用指南（快速上手、核心操作、常见场景）
7. 功能模块（各模块功能详细描述 —— **隔离的核心所在**）
8. 运维管理（日志、监控、告警、备份）
9. 常见问题（使用/配置/功能类问题解答）
10. 附录（术语表、接口清单、依赖清单、目录结构）；如配置扩展章节，编号顺延

---

## 源程序材料标准

- 竖向 A4，每页至少 50 行，最终 60–65 页
- 多份软著页数建议不同（60、62、64 页）
- 不添加页眉、页脚、行号、分隔符
- 长代码行避免自动换行（使用固定行高表格）
- 必须转 PDF 并校验实际页数
- **各份软著取材源文件不得重叠**

---

## 命名规范

| 规则 | 示例 |
| --- | --- |
| 名称要像真实产品，不像技术模块 | ✅ "广告投放管理系统" ❌ "AdTemplateService模块" |
| 名称直接反映核心功能 | ✅ "智能广告投放系统" ❌ "业务处理平台" |
| 不同软著名称差异要明显 | ✅ "投放系统" vs "素材管理系统" ❌ "平台A" vs "平台B" |
| 软著名称与技术没有强绑定 | ✅ "用户管理系统" ❌ "Spring Boot用户模块" |

---

## 注意事项

- 不伪造著作权人、开发完成日期、统一社会信用代码等主体信息
- 不在材料中泄露 API Key、Token、手机号、私有服务器地址（源程序提取默认脱敏，Step 5 会复查）
- 不申报他人作品：第三方库、开源项目代码、脚手架原有代码不得作为源程序材料，也不得删除其许可证/版权声明后使用
- 所有申报材料一律不出现开源协议、仓库地址和引用来源（自有开源项目由 Step 5 工具清除，业务用语不动）；发表状态一律按“未发表”，源程序取自上架版本
- 申请表“源程序量”填**全项目源码总行数**（`manual_spec.py` 统计），不是 60 页取材的行数
- 申请表“开发工具”填 IDE、编译器、构建工具等实际工具，不要填 React、Vue 这类技术栈名称
- 多份软著的开发完成日期可选择不同工作日（相差 1-3 天）
- 说明书内容必须与项目源码和实际功能一致；AIGC 去痕改写同样不得虚构功能、文件或数据
- 三份或多份软著之间源码取材绝对不能重复（会被审查）
- 每次申报或提交前，检查软著名称、版本号、著作权人、开发完成日期在所有材料中是否完全一致
