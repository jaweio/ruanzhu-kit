import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from aigc_check import collect  # noqa: E402


class AigcScopeTests(unittest.TestCase):
    def test_manifest_scope_excludes_legacy_and_source_material(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "auto-fill").mkdir()
            (root / "软件说明书.md").write_text("# 软件概述\n进入首页。", encoding="utf-8")
            (root / "申请表填报文案.md").write_text("# 申请表\n" + "真实功能。" * 20, encoding="utf-8")
            (root / "auto-fill" / "config.json").write_text(
                json.dumps({"step4_features": {"mainFunction": "真实功能。" * 20}}, ensure_ascii=False),
                encoding="utf-8")
            (root / "源程序提取").mkdir()
            (root / "源程序提取" / "程序.pdf").write_bytes(b"not scanned")
            legacy = root / "旧版未裁剪材料"
            legacy.mkdir()
            (legacy / "旧.md").write_text("旧版模板内容。" * 50, encoding="utf-8")
            (root / "材料上传清单.json").write_text(json.dumps({
                "_schema": "ruanzhu-kit.material-manifest.v1",
                "materials": {
                    "programPdf": {"path": "01/源程序提取/程序.pdf"},
                    "docPdf": {"path": "01/软件说明.pdf"},
                },
            }, ensure_ascii=False), encoding="utf-8")
            files = {p.relative_to(root).as_posix() for p in collect([root])}
            self.assertIn("软件说明书.md", files)
            self.assertIn("申请表填报文案.md", files)
            self.assertIn("auto-fill/config.json", files)
            self.assertNotIn("旧版未裁剪材料/旧.md", files)
            self.assertNotIn("源程序提取/程序.pdf", files)


if __name__ == "__main__":
    unittest.main()
