"""dashboard.py 相对 output_root 解析回归测试。

场景：config 的 output_root 写相对路径、材料上传清单.json 里记录绝对路径时，
dashboard.py 曾用相对 root 调 path.relative_to(root) 抛 ValueError。
_output_root 应把相对 output_root 解析为绝对路径，使扫描不依赖 CWD。
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from dashboard import _output_root  # noqa: E402


class TestOutputRoot(unittest.TestCase):
    def _write_cfg(self, tmp: Path, output_root: str) -> Path:
        materials = tmp / "soft-copyright-materials"
        (materials / "01-demo").mkdir(parents=True, exist_ok=True)
        cfg_path = materials / "ruanzhu.config.json"
        cfg_path.write_text(json.dumps({
            "output_root": output_root,
            "projects": [{"id": "01-demo", "name": "demo"}],
        }, ensure_ascii=False), encoding="utf-8")
        return cfg_path

    def test_relative_output_root_resolved_against_cfg_parent(self):
        # config 位于 <output_root>/ 内：cfg_path.parent 即 output_root 自身
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg_path = self._write_cfg(tmp, "soft-copyright-materials")
            root = _output_root(json.loads(cfg_path.read_text(encoding="utf-8")), cfg_path)
            self.assertTrue(root.is_absolute())
            self.assertEqual(root, (tmp / "soft-copyright-materials").resolve())
            # 清单绝对路径可以 relative_to root
            pdf = (root / "01-demo" / "提交材料" / "demo源码.pdf")
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(b"x")
            pdf.relative_to(root)

    def test_absolute_output_root_untouched(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            target = tmp / "materials-abs"
            target.mkdir()
            cfg_path = self._write_cfg(tmp, str(target))
            root = _output_root(json.loads(cfg_path.read_text(encoding="utf-8")), cfg_path)
            self.assertEqual(root, target)

    def test_missing_relative_root_falls_back_to_cwd_resolve(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg_path = self._write_cfg(tmp, "does-not-exist")
            cfg_path.unlink()
            cfg_path.write_text(json.dumps({"output_root": "does-not-exist", "projects": []},
                                           ensure_ascii=False), encoding="utf-8")
            root = _output_root(json.loads(cfg_path.read_text(encoding="utf-8")), cfg_path)
            self.assertTrue(root.is_absolute())


if __name__ == "__main__":
    unittest.main()
