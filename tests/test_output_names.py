import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from output_names import (manual_pdf_name, source_material_docx_name,
                          source_material_pdf_name, source_material_stem,
                          submission_dir, submission_form_path,
                          manual_page_window)


class OutputNameTests(unittest.TestCase):
    def test_short_name_is_used_for_delivery_files(self):
        project = {"name": "益搭智能移动协作系统", "short_name": "益搭智能", "document_kind": "mobile"}
        self.assertEqual(manual_pdf_name(project), "益搭智能-移动端软件说明.pdf")
        self.assertEqual(source_material_stem(project, 60), "益搭智能-移动端源码")
        self.assertEqual(source_material_pdf_name(project), "益搭智能-移动端源码.pdf")
        self.assertEqual(source_material_docx_name(project), "益搭智能-移动端源码.docx")

    def test_falls_back_to_full_name_and_sanitizes_path_chars(self):
        project = {"name": "桌面/协作:系统"}
        self.assertEqual(manual_pdf_name(project), "桌面-协作-系统软件说明.pdf")

    def test_explicit_endpoint_label_overrides_kind(self):
        project = {"short_name": "AI 协作", "document_kind": "desktop", "artifact_label": "后端"}
        self.assertEqual(manual_pdf_name(project), "AI 协作-后端软件说明.pdf")

    def test_final_materials_have_one_directory(self):
        project_dir = Path("/tmp/01-ai")
        self.assertEqual(submission_dir(project_dir), project_dir / "提交材料")
        self.assertEqual(submission_form_path("AI-后端源码.pdf"), "../提交材料/AI-后端源码.pdf")

    def test_manual_page_window_defaults_to_about_forty(self):
        self.assertEqual(manual_page_window({}, {}), (35, 45, 40))
        self.assertEqual(manual_page_window({"manual_page_target": 50, "manual_page_tolerance": 3}, {}), (47, 53, 50))

    def test_manual_page_window_rejects_malformed_values(self):
        self.assertEqual(manual_page_window({"manual_page_target": "bad"}, {}), (35, 45, 40))


if __name__ == "__main__":
    unittest.main()
