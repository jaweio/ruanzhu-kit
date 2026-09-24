import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workflow_smoke import run  # noqa: E402


class WorkflowSmokeTests(unittest.TestCase):
    def test_smoke_reports_formal_manifest_and_no_legacy_scan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_id = "01-demo"
            project_dir = root / project_id
            final_dir = project_dir / "提交材料"
            final_dir.mkdir(parents=True)
            (project_dir / "软件说明书.md").write_text("# 软件概述\nDemo software V1.0\n进入首页。", encoding="utf-8")
            (project_dir / "申请表填报文案.md").write_text("Demo software V1.0 申请表真实内容。" * 20, encoding="utf-8")
            (project_dir / "auto-fill").mkdir()
            (project_dir / "auto-fill" / "config.json").write_text(json.dumps({
                "step2_basic": {"softwareName": "Demo software", "version": "V1.0"},
                "step4_features": {
                "programPdf": "../提交材料/演示-后端源码.pdf",
                "docPdf": "../提交材料/演示-后端软件说明.pdf",
            }}), encoding="utf-8")
            from pypdf import PdfWriter
            from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
            for path in (final_dir / "演示-后端源码.pdf", final_dir / "演示-后端软件说明.pdf"):
                writer = PdfWriter(); page = writer.add_blank_page(width=100, height=100)
                font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                         NameObject("/Subtype"): NameObject("/Type1"),
                                         NameObject("/BaseFont"): NameObject("/Helvetica")})
                page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
                stream = DecodedStreamObject()
                stream.set_data(b"BT /F1 12 Tf 10 10 Td (Demo software V1.0) Tj ET")
                page[NameObject("/Contents")] = stream
                with path.open("wb") as handle:
                    writer.write(handle)
            (project_dir / "材料上传清单.json").write_text(json.dumps({
                "_schema": "ruanzhu-kit.material-manifest.v1",
                "materials": {
                    "programPdf": {"path": f"{project_id}/提交材料/演示-后端源码.pdf"},
                    "docPdf": {"path": f"{project_id}/提交材料/演示-后端软件说明.pdf"},
                },
            }, ensure_ascii=False), encoding="utf-8")
            cfg = root / "ruanzhu.config.json"
            cfg.write_text(json.dumps({"output_root": str(root), "projects": [{
                "id": project_id, "name": "Demo software", "short_name": "演示", "artifact_label": "后端",
                "version": "V1.0", "source_pages": 1,
            }]}), encoding="utf-8")
            result = run(cfg)
            # 朱雀检测是必过闸门：未检测、用户也未两次明确拒绝时，正式清单不通过
            self.assertFalse(result["projects"][0]["formal_manifest"])
            self.assertTrue(any("朱雀" in c for c in result["projects"][0]["manifest_checks"]))
            (project_dir / ".zhusque-declined.json").write_text(json.dumps({"declines": [
                {"reason": "用户拒绝上传", "source": "chat"}, {"reason": "用户再次拒绝", "source": "chat"},
            ]}, ensure_ascii=False), encoding="utf-8")
            result = run(cfg)
            self.assertTrue(result["projects"][0]["formal_manifest"])
            self.assertEqual(result["copyright"]["high"], 0)


if __name__ == "__main__":
    unittest.main()
