"""配置缺失时，任何生成文件都不得出现占位文字；缺失只体现在校验结果里。"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import application_form  # noqa: E402
import generate_docs  # noqa: E402

MARKER = re.compile(r"【[^】]*(?:待|预留|占位)[^】]*】|按项目实际(?:填写|依赖填写|支持平台填写|情况补充)")


class NoPlaceholderOutputTests(unittest.TestCase):
    def assert_clean(self, root):
        dirty = []
        for path in Path(root).rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json", ".html", ".txt"}:
                for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if MARKER.search(line):
                        dirty.append(f"{path.relative_to(root)}:{no}: {line.strip()[:80]}")
        self.assertEqual(dirty, [], "生成文件含占位文字：\n" + "\n".join(dirty))

    def test_bare_config_generates_no_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "out"
            cfg = {"output_root": str(root), "projects": [{"id": "01-a", "name": "订单管理系统"}]}
            cfg_path = Path(td) / "ruanzhu.config.json"
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            for script in ("generate_docs.py", "application_form.py"):
                args = [sys.executable, str(SCRIPTS / script), "--config", str(cfg_path)]
                if script == "generate_docs.py":
                    args.append("--skip-aigc")
                subprocess.run(args, check=True, capture_output=True, cwd=td)
            self.assert_clean(root)
            self.assertFalse((root / "待补充信息清单.md").exists())
            self.assertIn("开发完成日期", (root / "缺失信息清单.md").read_text(encoding="utf-8"))
            self.assertNotIn("著作权人", (root / "缺失信息清单.md").read_text(encoding="utf-8"))

    def test_default_template_generates_no_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "ruanzhu.config.json"
            subprocess.run([sys.executable, str(SCRIPTS / "create_config.py"), "--output", str(cfg_path)],
                           check=True, capture_output=True)
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.assertNotIn("【", cfg_path.read_text(encoding="utf-8"))
            cfg["output_root"] = str(Path(td) / "out")
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            for script, extra in (("generate_docs.py", ["--skip-aigc"]), ("application_form.py", [])):
                subprocess.run([sys.executable, str(SCRIPTS / script), "--config", str(cfg_path), *extra],
                               check=True, capture_output=True, cwd=td)
            self.assert_clean(Path(td) / "out")

    def test_templates_contain_no_placeholders(self):
        root = SCRIPTS.parent
        for rel in ("assets/ruanzhu.config.example.json", "scripts/auto-fill/config.template.json"):
            self.assertNotIn("【", (root / rel).read_text(encoding="utf-8"), rel)

    def test_missing_fields_are_reported_by_validation(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "01-a"
            form = application_form.build({}, {"id": "01-a", "name": "订单管理系统"}, Path(td), None, None)
            self.assertEqual(form["step2_basic"]["copyrightHolder"], "")
            fields = {i["field"] for i in application_form.validate(form, d, None) if i["msg"] == "未填写"}
        self.assertTrue({"completionDate", "devTools", "sourceLines"} <= fields)
        self.assertNotIn("copyrightHolder", fields)

    def test_application_form_explains_account_sourced_holder(self):
        form = application_form.build({}, {"id": "01-a", "name": "订单管理系统"}, Path("/tmp"), None, None)
        text = application_form.copy_md(form, application_form.validate(form, Path("/tmp/01-a"), None), {"name": "订单管理系统"})
        self.assertIn("由登录版权中心账号带入", text)

    def test_legacy_confirmation_prompts_are_not_exported(self):
        cfg = {
            "copyright_holder": "待确认（申请人提供著作权人全称）",
            "development_completed_date": "待确认（申请人提供YYYY-MM-DD）",
        }
        form = application_form.build(cfg, {"id": "01-a", "name": "订单管理系统"}, Path("/tmp"), None, None)
        self.assertEqual(form["step2_basic"]["copyrightHolder"], "")
        self.assertEqual(form["step2_basic"]["completionDate"], "")
        text = generate_docs.application_copy({"id": "01-a", "name": "订单管理系统"}, cfg)
        self.assertNotIn("待确认", text)

    def test_application_copy_omits_missing_rows(self):
        text = generate_docs.application_copy({"id": "01-a", "name": "订单管理系统"}, {})
        self.assertNotIn("著作权人", text)
        self.assertNotIn("【", text)
        full = generate_docs.application_copy(
            {"id": "01-a", "name": "订单管理系统", "summary": "订单录入与审核。"},
            {"copyright_holder": "某某科技有限公司", "development_completed_date": "2026-09-01"})
        self.assertIn("| 著作权人 | 某某科技有限公司 |", full)
        self.assertIn("## 软件主要功能\n订单录入与审核。", full)


if __name__ == "__main__":
    unittest.main()
