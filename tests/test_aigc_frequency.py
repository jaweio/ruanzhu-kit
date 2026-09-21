import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from aigc_check import analyze
from aigc_rewrite import clean_text


class AigcFrequencyTests(unittest.TestCase):
    def test_reports_common_term_frequency_and_generic_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "说明书.md"
            text = "# 系统优势\n\n" + "系统可以处理模块。" * 40
            path.write_text(text, encoding="utf-8")
            result = analyze(path)
            self.assertGreater(result["stats"]["common_terms"]["系统"], 20)
            self.assertTrue(result["stats"]["frequency_warnings"])
            self.assertGreater(result["stats"]["heading_blacklist_hits"], 0)

    def test_rewrite_prunes_legacy_template_sections(self):
        text = ("## 设计原则\n\n| 原则 | 说明 |\n|---|---|\n| 易用性 | 提供清晰的界面和操作流程。 |\n"
                "| 模块化 | 按功能边界拆分模块，便于维护。 |\n"
                "| 可扩展性 | 支持后续新增功能和外部集成。 |\n"
                "| 安全性 | 对关键数据、权限和操作进行约束。 |\n"
                "| 可追溯 | 保留必要日志、记录和诊断信息。 |\n"
                "## 核心特性\n\n真实页面入口。\n")
        new, hits = clean_text(text)
        self.assertNotIn("设计原则", new)
        self.assertIn("核心特性", new)
        self.assertTrue(any("旧版通用模板" in key for key in hits))


if __name__ == "__main__":
    unittest.main()
