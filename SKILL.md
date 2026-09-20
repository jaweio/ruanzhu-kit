---
name: ruanzhu-kit
description: 软著工具箱。Use when Codex or Claude needs to analyze a software project and generate reusable Chinese software copyright registration materials, including project splitting, naming, application-form copy, software manuals with clickable table of contents, source-code DOCX/PDF extracts, validation records, copyright-risk checks and removal of all repository/open-source traces (GitHub/Gitee URLs, license headers, badges; third-party code auto-excluded), AIGC (AI-generated text) style detection and removal for manuals and application copy, and packaged deliverables based on a configurable workflow. Also covers auto-filling the R11 form on register.ccopyright.com.cn by driving the user's already logged-in Chrome through the browser extension (or computer-use); it stops at saving a draft and never submits.
---

# 软著工具箱

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
Step 4  生成材料    →  截图整理 screenshots.py → generate_docs.py（按素材生成）+ generate_source_docx.py
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

---

## Step 4 — 生成材料

```bash
# 截图：Web 项目先自动拍，再整理编号（非 Web 项目跳过 capture.py，人工截图放进 用户截图/）
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
```

`generate_source_docx.py` 默认：跳过第三方文件；清除自有代码的许可证头、仓库地址和开源注释（`"scrub_open_source"`）；脱敏密钥、手机号、邮箱、内网 IP（`"redact"`）。

每份软著生成：

1. `软件说明书.md`（Step 7 渲染为 PDF）
2. `申请表填报文案.md`
3. `源码材料清单.md`
4. `源程序提取/源程序鉴别材料-XX页.docx`

### 4.0 说明书素材与截图

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

`screenshots.py` 只整理、编号、对号，不生成图片；对不上模块的截图会提示，改文件名或手工改清单的 `module` 字段即可。

### 4.1 说明书文风要求（必读）

脚本生成的是模板骨架。**产出终稿前，必须按 [references/writing-style.md](references/writing-style.md) 的规范人工充实并改写全部散文章节**，要点：

- **功能按“（一）功能说明 /（二）操作步骤 /（三）异常处理”写**：步骤带界面真实文字、取值约束、失败分支——朱雀实测唯一稳定判人工的写法（0.16），`generate_docs.py` 已按此生成骨架
- 结构禁忌：密集括号补注、“**X**：”粗体排比、“**Qn：**”FAQ 连排、分号收尾的列表（实测 0.78–0.999 判 AI，即使事实很多）
- 黑名单句式（“覆盖…体系”“提供…能力”“沉淀为”“核心意义在于”“无论是…还是…都”等）清零
- 每段至少一个真实事实（界面文字/路径/版本号/错误码）——为了真实，不指望它降分；**禁止编造**
- 表格为可读性服务，不当降分手段（实测 0.24–0.997 不稳定）；正式书面语即可，不必刻意口语化
- 写完后在 Step 6 用 `aigc_check.py` 量化验证，不靠自我感觉

### 4.2 说明书隔离要求

| 章节 | 隔离要求 |
| --- | --- |
| 软件概述 | 定位描述只涉及本软著核心功能，不提其他软著的功能 |
| 功能模块 | 所有功能点必须在本软著的功能边界内 |
| 技术特点 | 技术亮点要与本软著的核心功能挂钩 |
| 接口清单 | 只列本软著相关的接口（如有） |

### 4.3 多份软著说明书页数建议

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
| 自有代码（版权人是著作权人或 `self_aliases`） | 提取时自动删除：文件头许可证/版权块、含协议文本或引用标记（参考自/摘自/forked from…）的注释行、仓库/徽章/博客地址、`git clone` 类命令；业务注释保留 |
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
2. `软件说明书.pdf`（提交件，含可点击目录、页眉页码；由 md 渲染，不经 docx）
3. `申请表填报文案.md`（application_form.py 生成，与填表配置同源）
4. `源码材料清单.md`
5. `截图清单.json` + `截图/`（有截图时）
6. `源程序提取/源程序DOCX生成报告.md`（含跳过的第三方文件、脱敏与清除统计）
7. `源程序提取/源程序鉴别材料-XX页.docx`（编辑稿）
8. `源程序提取/源程序鉴别材料-XX页.pdf`（提交件）
9. `auto-fill/config.json` + `auto-fill/长文本/`（填表用）
10. `填表操作计划.md`（form_plan.py 生成）
11. `AIGC检测报告.md`（内部留档，不提交）
12. `AIGC改写任务单.md`（内部留档，不提交）
13. `版权风险检查报告.md`（位于 output_root，内部留档，不提交）
14. `看板.html`（位于 output_root，总览用，不提交）
15. `说明书素材.json` + `预览.md`（位于 output_root，内部留档）

---

## 说明书标准（10 章结构）

0. 说明书 PDF 每页带页眉（软件全称 + 版本号）和“第 X 页 / 共 N 页”，封面页不带（render_pdfs.py 自动加）
1. 软件概述（定位、目标、特性、版本）
2. 软件架构（架构图、分层说明、技术选型）
3. 环境要求（开发环境、运行环境、第三方依赖）
4. 安装部署（依赖安装、启动方式、构建发布）
5. 配置说明（核心配置项、配置文件、参数说明）
6. 使用指南（快速上手、核心操作、常见场景）
7. 功能模块（各模块功能详细描述 —— **隔离的核心所在**）
8. 运维管理（日志、监控、告警、备份）
9. 常见问题（使用/配置/功能类问题解答）
10. 附录（术语表、接口清单、依赖清单、目录结构）

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
