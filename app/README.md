# 软著工具箱（桌面版）

基于 ruanzhu-kit 的 macOS 应用：选择源码目录 → 填基本信息 → AI 分析 → AI 生成材料 → 编辑说明书 → 导出 PDF 与核验 → 浏览器填表（只存草稿）。

## 运行

```bash
cd app
npm install
npm start
```

打包（未签名 .app，输出到 `dist/mac-arm64/`）：

```bash
CSC_IDENTITY_AUTO_DISCOVERY=false npm run dist
```

## 依赖

- **Python 3 + python-docx + pypdf**：自动查找 Homebrew / 登录 shell 中的 python3；找不到时在“项目与环境”页点“一键安装 Python 依赖”，会在 App 数据目录建私有 venv。
- **Claude Code（`claude` 命令）**：AI 步骤复用本机已安装、已登录的 Claude Code，App 不再打包一份（省 208 MB）。也可在“设置”里填写 Anthropic API Key。
- **Pandoc、Chrome**：`render_pdfs.py` 生成 PDF 用；填表使用本机 Chrome。

## 设计要点

- 脚本来自上级目录 `../scripts`（开发）或 `Resources/kit`（打包），与 Skill 共用同一份实现。
- AI 通过 Agent SDK 执行 SKILL.md 的 Step 1–6：只读工具自动放行；写文件仅限项目的 `soft-copyright-materials/`；Bash 拒绝删除、git 改写、联网、安装依赖；不加载用户自己的 CLAUDE.md / hooks；清除父进程继承的 Claude/Anthropic 环境变量。
- 界面只读写材料目录；填表停在保存草稿，正式提交由用户本人操作。
