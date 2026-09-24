import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from spec_gate import check  # noqa: E402

SPEC = {"name": "星游游戏盒子", "modules": [
    {"name": "游戏列表", "pages": ["pages/game/list"]},
    {"name": "游戏详情", "pages": ["pages/game/detail"]},
]}


def page(name, n):
    body = "\n".join(f"    <view class=\"row-{i}\">{{{{ item.field_{name}_{i} }}}} 第 {i} 项</view>" for i in range(n))
    return f"<template>\n  <view>\n{body}\n  </view>\n</template>\n"


def make_project(root, pages_json=None, files=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pages.json").write_text(pages_json or json.dumps({
        "pages": [{"path": "pages/game/list"}],
        "subPackages": [{"root": "pages/game", "pages": [{"path": "detail"}]}],
    }), encoding="utf-8")
    for rel, text in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class SpecGateTests(unittest.TestCase):
    def test_real_pages_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_project(root, files={"pages/game/list.vue": page("list", 60), "pages/game/detail.vue": page("detail", 60)})
            result = check(root, SPEC, min_lines=100)
            self.assertTrue(result["ok"], result["errors"])
            self.assertGreaterEqual(result["code_lines"], 120)

    def test_missing_unregistered_and_stub_pages_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_project(root, pages_json='{\n  // 注释\n  "pages": [{"path": "pages/game/list"}]\n}',
                         files={"pages/game/list.vue": "<template><view>TODO</view></template>\n"})
            errors = "\n".join(check(root, SPEC, min_lines=10)["errors"])
            self.assertIn("未登记", errors)
            self.assertIn("不存在", errors)
            self.assertIn("空壳", errors)

    def test_padding_by_duplication_and_low_line_count_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy = "<template>\n" + "\n".join(["    <view class=\"row\">{{ item.name }} 重复的内容行</view>"] * 80) + "\n</template>\n"
            make_project(root, files={"pages/game/list.vue": copy, "pages/game/detail.vue": copy,
                                      "node_modules/x/index.js": page("vendor", 5000)})
            result = check(root, SPEC)
            errors = "\n".join(result["errors"])
            self.assertIn("重复代码", errors)
            self.assertIn("不足 3000 行", errors)  # node_modules 不计入自有代码

    def test_not_uni_app_and_build_gate(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIn("pages.json", check(Path(td), SPEC)["errors"][0])
            root = Path(td) / "app"
            make_project(root, files={"pages/game/list.vue": page("list", 60), "pages/game/detail.vue": page("detail", 60)})
            self.assertFalse(check(root, SPEC, min_lines=100, require_build=True)["ok"])
            (root / "dist/build/h5").mkdir(parents=True)
            (root / "dist/build/h5/index.html").write_text("<html></html>", encoding="utf-8")
            self.assertTrue(check(root, SPEC, min_lines=100, require_build=True)["ok"])


if __name__ == "__main__":
    unittest.main()
