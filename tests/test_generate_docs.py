import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_docs
import render_pdfs
import aigc_rewrite


class GenerateDocsTests(unittest.TestCase):
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
            self.assertTrue((root / "01-复杂系统" / "说明书章节" / "11-数据治理.md").exists())

    def test_generation_does_not_require_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = {"id": "01-离线生成", "name": "离线生成"}
            generate_docs.write_project(root, {}, project)
            self.assertTrue((root / "01-离线生成" / "软件说明书.md").exists())
            self.assertTrue((root / "01-离线生成" / "说明书章节" / "10-附录.md").exists())

    def test_regeneration_removes_stale_generated_chapters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chapters = root / "01-离线生成" / "说明书章节"
            chapters.mkdir(parents=True)
            stale = chapters / "11-旧的可选章节.md"
            stale.write_text("# 11 旧的可选章节\n", encoding="utf-8")
            generate_docs.write_project(root, {}, {"id": "01-离线生成", "name": "离线生成"})
            self.assertFalse(stale.exists())
            self.assertTrue((chapters / "10-附录.md").exists())

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
