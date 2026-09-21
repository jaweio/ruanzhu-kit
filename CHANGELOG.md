# 版本记录

## 未发布

- 新增 `zhusque_check.py`：可选调用 EdgeOne Makers 兼容 OpenAI 的接口进行朱雀风格文风辅助检测。
- API Key 只从环境变量或本机 macOS Keychain 读取；未绑定时提示用户自行生成，检测前必须显式确认上传。
- 检测改为显式触发，并增加规范化文本块指纹和本机结果缓存，避免重复全文请求；支持 `--no-cache` 强制重测。
- `generate_docs.py` 首次生成后默认自动运行离线 AIGC 机械清理；新增 `zhusque_check.py finalize`，正文确认后执行一次全量朱雀检测并记录最终文本指纹。
- 新增 `prepare_demo_data.py`：从项目源码和说明书素材生成合成演示数据方案，跳过敏感字段和“测试/示例”占位词，供本地页面/API 创建数据后截图。
- 说明书改为“默认十章、按项目扩展”：支持 `projects[].extra_chapters`；材料分析、生成、检查和 PDF 流程明确不要求先启动前后端，运行项目仅用于截图、页面核验和演示数据创建。
- `render_pdfs.py` 增加 `reference` / `clean` 两种说明书排版样式，默认使用参考样式。
- 新增 `project_runtime.py`：仅在显式 `--allow-run` 时启动本地前后端，并提供状态、健康检查和停止。
- 新增 `apply_demo_data.py`：本地 API 演示数据默认预览，显式允许后写入，自动保存逆序回滚记录。
- 新增 `softcopyright_branch.py`：创建独立软著分支/工作树并检查多份材料源码重叠。
- `screenshots.py` 新增清单完整性检查，发现缺图、空图、未匹配项和缺失模块时可失败退出。
- `generate_source_docx.py` 默认对输出材料裁剪普通注释、导入/include/use 声明和连续空行；支持 `source_material` 配置及 `--keep-comments`、`--keep-imports` 覆盖，原项目源文件不变。
- 新增 `source_preview.py`：在生成 DOCX 前以本地 HTML 预览裁剪统计、跳过文件和脱敏样本；`generate_source_docx.py --preview` 可同步生成。
- 说明书默认内容不再填入硬件、权限、日志、安装命令、测试结果等未经核验的事实；缺失项改为待核验标记，并支持从项目配置提供真实值。
- `manual_spec.py` 从源码提取后端接口方法/路径/文件/行号，识别实际 Knife4j/OpenAPI 依赖并生成截图证据计划。
- `screenshots.py` 为后端截图写入 `evidence_id`，`--check --fail-on-missing` 可校验成功响应、4xx 错误响应、运行日志以及实际启用的调试页。
- AIGC 报告增加“可以/系统/模块”高频统计，识别通用优势/核心价值标题和“整套业务闭环是完整的”等生成式表达。

## 1.0.1 — 2026-09-20

- 新增每次 Skill 新任务开始前检查最新正式 Release 的步骤。
- 新增 check_update.py：Git / 压缩包安装均支持；默认 4 秒网络超时，检查失败不阻塞任务。
- 发现新版只提示，不自动改写本地文件；无新版时继续工作。
- 增加版本比较、超时、限流、异常响应及不改写文件等 10 项测试。

## 1.0.0 — 2026-09-20

- 首次公开发布，基于当日本地 ruanzhu-manager 的 51 个文件。
- 添加 MIT 许可证、安装/更新说明、Git 安装管理工具及可复现的 `.skill` 打包工具。
- 添加版本号、依赖说明、更新保护测试和发布校验文件。
- PDF 工具检测移除个人目录硬编码，支持环境变量和 PATH。
- 修复备用填表脚本单独传入 `--check` 时被误当作配置文件名的问题。
- 保留原功能和排版；README 明确记录日期/发表状态旧规则、来源检查与文风评分等限制。
