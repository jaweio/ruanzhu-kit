import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_docs
import render_pdfs
import aigc_rewrite


class GenerateDocsTests(unittest.TestCase):
    def test_application_copy_uses_declared_source_file_count(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = repo / "src" / "Main.java"
            source.parent.mkdir()
            source.write_text("one\ntwo\nthree\n", encoding="utf-8")
            spec = {"repo": str(repo), "stats": {"source_lines": 1, "source_files": 1}}
            project = {"name": "示例", "source_count_mode": "source_files",
                       "source_files": ["src/Main.java"]}
            copy = generate_docs.application_copy(project, {}, spec)
            self.assertIn("3 行（1 个源文件，按本次申报清单逐文件统计）", copy)
            self.assertNotIn("1 行（1 个源文件，manual_spec.py 统计）", copy)

    def test_default_chapters_can_be_extended(self):
        project = {
            "id": "01-复杂系统",
            "name": "复杂系统",
            "extra_chapters": [{
                "title": "数据治理",
                "intro": "说明数据生命周期。",
                "sections": [{"title": "数据归档", "content": "按照业务状态归档记录。"}],
            }],
        }
        names = generate_docs.chapter_names(project)
        self.assertEqual(len(names), 11)
        text = generate_docs.manual(project, {}, shots={})
        self.assertIn("# 11 数据治理", text)
        self.assertIn("## 11.1 数据归档", text)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_docs.write_project(root, {}, project)
            # 空的默认章节被省略后，扩展章节按实际章序编号，文件名与正文标题一致
            files = list((root / "01-复杂系统" / "说明书章节").glob("*-数据治理.md"))
            self.assertEqual(len(files), 1)
            number = int(files[0].name[:2])
            self.assertTrue(files[0].read_text(encoding="utf-8").startswith(f"# {number} 数据治理"))

    def test_generation_does_not_require_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = {"id": "01-离线生成", "name": "离线生成"}
            generate_docs.write_project(root, {}, project)
            self.assertTrue((root / "01-离线生成" / "软件说明书.md").exists())
            chapters = sorted((root / "01-离线生成" / "说明书章节").glob("*.md"))
            self.assertTrue(chapters)  # 没有内容的章节整章省略，不输出空壳
            self.assertTrue(all(c.read_text(encoding="utf-8").strip().count("\n") >= 1 for c in chapters))

    def test_regeneration_removes_stale_generated_chapters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chapters = root / "01-离线生成" / "说明书章节"
            chapters.mkdir(parents=True)
            stale = chapters / "11-旧的可选章节.md"
            stale.write_text("# 11 旧的可选章节\n", encoding="utf-8")
            generate_docs.write_project(root, {}, {"id": "01-离线生成", "name": "离线生成"})
            self.assertFalse(stale.exists())
            self.assertTrue((chapters / "01-软件概述.md").exists())

    def test_manual_spec_false_disables_monorepo_fallback(self):
        project = {"id": "p", "name": "P", "manual_spec": False}
        self.assertIsNone(generate_docs.load_spec({}, Path("/tmp"), project))

    def test_missing_facts_are_not_filled_with_generic_runtime_claims(self):
        text = generate_docs.manual({"id": "p", "name": "P"}, {})
        self.assertNotIn("双核及以上", text)
        self.assertNotIn("软件应记录启动、配置、核心操作", text)
        self.assertNotIn("待核验", text)
        self.assertNotIn("待填写", text)
        self.assertNotIn("待补充", text)

    def test_internal_source_map_is_not_rendered_in_manual(self):
        text = generate_docs.manual({
            "id": "p", "name": "P", "version": "V1.0",
            "source_map": [["HTTP API", "server/cmd/server/main.go"]],
            "architecture_overview": "入口位于 server/cmd/server/main.go，通过 app/(auth)/login.tsx 进入。",
        }, {})
        self.assertNotIn("源码范围", text)
        self.assertNotIn("源码位置", text)
        self.assertNotIn("源码文件", text)
        self.assertNotIn("源码或界面", text)
        self.assertNotIn("server/cmd/server/main.go", text)
        self.assertNotIn("app/(auth)/login.tsx", text)

    def test_manual_safe_keeps_screenshot_links(self):
        text = generate_docs.manual({
            "id": "p", "name": "P",
            "modules": [["核心功能", "查看首页。"]],
            "screenshots": [{"file": "截图/01-首页.png", "title": "首页"}],
        }, {}, shots={"核心功能": [{"no": "01", "title": "首页", "file": "截图/01-首页.png"}]})
        self.assertIn("![01 首页](截图/01-首页.png)", text)

    def test_manual_safe_keeps_loopback_api_url(self):
        original = "GET http://127.0.0.1:18080/ai/coding/capabilities"
        self.assertEqual(generate_docs.manual_safe(original), original)

    def test_manual_safe_preserves_marked_virtual_path_only(self):
        text = "path={{virtual-path:src/Order.java}}；内部文件 src/main/Secret.java"
        rendered = generate_docs.manual_safe(text)
        self.assertIn("path=src/Order.java", rendered)
        self.assertNotIn("src/main/Secret.java", rendered)
        self.assertIn("对应业务模块", rendered)
        with self.assertRaises(ValueError):
            generate_docs.manual_safe("{{virtual-path:src/../secret}}")

    def test_module_keeps_all_real_screenshots(self):
        text = generate_docs.manual({
            "id": "p", "name": "P",
            "modules": [["核心功能", "查看首页。"]],
        }, {}, shots={"核心功能": [
            {"no": "图 7-1", "title": "首页", "file": "截图/7-1.png"},
            {"no": "图 7-2", "title": "首页详情", "file": "截图/7-2.png"},
        ]})
        self.assertIn("![图 7-1 首页](截图/7-1.png)", text)
        self.assertIn("![图 7-2 首页详情](截图/7-2.png)", text)

    def test_source_page_without_errors_does_not_emit_generic_error_placeholder(self):
        spec = {"pages": [{"module": "任务看板", "elements": ["任务"], "steps": ["打开任务"]}]}
        text = generate_docs.manual({"id": "p", "name": "P"}, spec)
        self.assertNotIn("页面素材未抽取到错误码", text)
        self.assertNotIn("运行核验时记录实际返回", text)

    def test_environment_requirements_use_env_facts_instead_of_placeholders(self):
        text = generate_docs.manual({
            "id": "p", "name": "P",
            "env": {
                "run_hardware": "Apple Silicon Mac，8GB 内存",
                "dev_hardware": "Apple Silicon Mac，16GB 内存",
                "run_os": "macOS 13 或更高版本",
                "run_support": "Electron 桌面运行时",
            },
            "permissions": [["网络访问", "连接工作区 API"]],
        }, {})
        self.assertIn("Apple Silicon Mac，8GB 内存", text)
        self.assertIn("macOS 13 或更高版本", text)
        self.assertIn("连接工作区 API", text)
        self.assertNotIn("实际硬件要求】", text)
        self.assertNotIn("实际运行环境】", text)
        self.assertNotIn("实际权限要求】", text)

    def test_manual_safe_does_not_break_package_commands(self):
        self.assertIn("@eadart/mobile", generate_docs.manual_safe("pnpm --filter @eadart/mobile ios:device"))

    def test_rest_api_appendix_renders_curated_data_structures(self):
        text = generate_docs.manual({
            "id": "p", "name": "P", "version": "V1.0",
            "api_examples": [{
                "method": "POST", "path": "/api/issues",
                "purpose": "创建问题",
                "auth": "需要登录",
                "request_fields": [["title", "string", "标题"]],
                "response_fields": [["id", "string", "标识"]],
                "status_codes": [["201", "创建成功"]],
            }],
        }, {})
        self.assertIn("## 10.2 核心 REST API 数据结构", text)
        self.assertIn("### API-1 POST /api/issues", text)
        self.assertIn("| title | string | 标题 |", text)
        self.assertIn("| 201 | 创建成功 |", text)
        self.assertNotIn("对应业务模块", text)

    def test_compact_api_appendix_keeps_shared_rules_once(self):
        common = [["200", "分析完成"], ["400", "参数不合法"]]
        text = generate_docs.rest_api_section({
            "api_reference_style": "compact",
            "api_common_auth": "本机或持有 token",
            "api_common_status": common,
            "api_shared_rules": "本节统一要求本机或持有 token；输入错误为 400。",
            "api_examples": [
                {"method": "POST", "path": "/api/check", "title": "检查输入",
                 "scenario": "提交 text 后核对位置。", "auth": "本机或持有 token",
                 "request_fields": [["text", "文本", "不超过 20 字"]],
                 "response_fields": [["findings", "数组", "命中位置"]],
                 "status_codes": common, "notes": "不返回原文。"},
                {"method": "GET", "path": "/api/status", "title": "查询状态",
                 "auth": "本机或持有 token", "response_fields": [["ready", "布尔", "是否就绪"]],
                 "status_codes": [["503", "尚未就绪"]]},
            ],
        })
        self.assertIn("提交 text 后核对位置。", text)
        self.assertIn("| 请求 | text | 文本 | 不超过 20 字 |", text)
        self.assertEqual(text.count("本机或持有 token"), 1)
        self.assertNotIn("| 200 | 分析完成 |", text)
        self.assertIn("| 503 | 尚未就绪 |", text)

    def test_curated_module_chapter_replaces_repeated_overview(self):
        text = generate_docs.manual({
            "id": "p", "name": "P", "modules": [["扫描", "读取输入"]],
            "module_overview": "先检查文件清单，再查看结果。",
            "module_manual": "## 7.2 扫描\n\n提交文件后读取计数，空清单会被拒绝。",
        }, {})
        self.assertIn("## 7.1 模块一览\n先检查文件清单", text)
        self.assertIn("## 7.2 扫描", text)
        self.assertNotIn("| 扫描 | 读取输入 |\n\n## 7.2", text)

    def test_curated_feature_and_operation_prose_replaces_tables(self):
        text = generate_docs.manual({
            "id": "p", "name": "P", "document_kind": "backend",
            "modules": [["扫描", "读取输入"]],
            "operations": [["扫描", "提交文件", "返回计数"]],
            "core_features_text": "先提交虚拟文件，再按返回的摘要核对输入。",
            "operations_text": "核对时先保存摘要；内容变更后，摘要随之变化。",
        }, {})
        self.assertIn("先提交虚拟文件，再按返回的摘要核对输入。", text)
        self.assertIn("核对时先保存摘要；内容变更后，摘要随之变化。", text)
        self.assertNotIn("| 扫描 | 读取输入 |", text.split("## 1.4 核心特性", 1)[1].split("## 1.5", 1)[0])
        self.assertNotIn("| 扫描 | 提交文件 | 返回计数 |", text)

    def test_can_omit_redundant_feature_and_quick_start_sections(self):
        text = generate_docs.drop_empty_sections(generate_docs.manual({
            "id": "p", "name": "P", "document_kind": "backend",
            "modules": [["扫描", "读取输入"]],
            "quick_start": ["提交输入"],
            "operations_text": "提交输入后核对摘要。",
            "omit_core_features": True,
            "omit_quick_start": True,
        }, {}))
        self.assertNotIn("核心特性", text)
        self.assertNotIn("快速上手", text)
        self.assertIn("提交输入后核对摘要。", text)

    def test_architecture_prose_can_replace_class_inventory_table(self):
        text = generate_docs.manual({
            "id": "p", "name": "P", "document_kind": "backend",
            "architecture_layers": [["接入", "处理请求"]],
            "architecture_layers_text": "请求先经过权限检查，再交给只读分析服务。",
        }, {})
        section = text.split("## 2.2 分层架构", 1)[1].split("## 2.3", 1)[0]
        self.assertIn("请求先经过权限检查", section)
        self.assertNotIn("| 接入 | 处理请求 |", section)

    def test_aigc_cleanup_keeps_following_extended_chapter(self):
        text = (
            "## 10.3 测试用例\n"
            "| 编号 | 场景 | 实际结果 |\n| --- | --- | --- |\n"
            "| TC-001 | 健康检查 | 返回 200。 |\n\n"
            "# 11 接口调用与数据对象\n\n"
            "## 11.1 请求上下文\n\n"
            "根据会话和工作区角色校验请求。\n"
        )
        cleaned, hits = aigc_rewrite.clean_text(text)
        self.assertIn("# 11 接口调用与数据对象", cleaned)
        self.assertIn("## 11.1 请求上下文", cleaned)

    def test_configured_development_goals_are_rendered(self):
        text = generate_docs.manual({
            "id": "p", "name": "P",
            "development_goals": ["统一登录与工作区入口。", "集中处理任务协作信息。"],
        }, {})
        self.assertIn("- 统一登录与工作区入口。", text)
        self.assertIn("- 集中处理任务协作信息。", text)
        self.assertNotIn("待改写：写 2-4 个本软件要解决的具体问题", text)

    def test_reference_materials_are_audited_without_copying_unverified_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            (reference / "instructions").mkdir(parents=True)
            (reference / "screenshots").mkdir()
            (reference / "instructions" / "01-系统概述.md").write_text("# 旧材料\n", encoding="utf-8")
            generate_docs.reference_material_report({"reference_materials": {"root": str(reference)}}, root)
            report = (root / "参考材料核对.md").read_text(encoding="utf-8")
            self.assertIn("章节材料：1 份", report)
            self.assertIn("不复制参考项目专属名称", report)

    def test_pdf_chapter_list_reads_extended_markdown_headings(self):
        markdown = "# 目录\n\n# 软件概述\n正文\n# 附录\n正文\n# 11 数据治理\n正文\n"
        self.assertEqual(render_pdfs.chapter_titles(markdown), ["软件概述", "附录", "数据治理"])
        html = render_pdfs.anchor_h1(
            "<h1>11 数据治理</h1>", "复杂系统", "reference"
        )
        self.assertIn("01-数据治理", html)
        self.assertNotIn("复杂系统 - 数据治理", html)


if __name__ == "__main__":
    unittest.main()


class DropEmptySectionsTests(unittest.TestCase):
    def test_empty_chapter_removed_from_body_and_toc(self):
        from generate_docs import drop_empty_sections
        md = ("# 目录\n\n- [1. 概述](#概述)\n- [2. 运维管理](#运维管理)\n- [3. 附录](#附录)\n\n"
              "# 概述\n\n## 1.1 简介\n正文。\n\n# 运维管理\n\n## 8.1 日志\n| a | b |\n| --- | --- |\n\n"
              "# 附录\n\n## 10.1 截图\n图。\n")
        out = drop_empty_sections(md)
        self.assertNotIn("运维管理", out)
        self.assertIn("- [2. 附录](#附录)", out)
        self.assertIn("## 2.1 截图", out)

    def test_empty_sections_removed_and_renumbered(self):
        from generate_docs import drop_empty_sections
        md = ("# 配置说明\n\n## 5.1 配置概述\n\n\n## 5.2 配置项清单\n| 配置项 | 作用 |\n| --- | --- |\n\n"
              "## 5.3 存储\n数据保存在本机。\n\n# 使用指南\n\n## 6.1 快速上手\n打开首页。\n")
        out = drop_empty_sections(md)
        self.assertNotIn("配置概述", out)
        self.assertNotIn("配置项清单", out)
        # 片段里“配置说明”是第 1 章：小节按删除后的实际章序重排
        self.assertIn("## 1.1 存储", out)
        self.assertIn("## 2.1 快速上手", out)

    def test_hardware_without_values_is_blank(self):
        from environment_profile import _hardware
        self.assertEqual(_hardware({"recommended": True, "cpu_cores": ""}), "")
        self.assertIn("CPU", _hardware({"recommended": True, "cpu_cores": "4"}))
