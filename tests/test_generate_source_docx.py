import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_source_docx
from copyright_check import _own_tokens


SELF_FILE = '''\
/*
 * Copyright (c) 2026 Demo Co.,Ltd.
 * Licensed under the Apache License, Version 2.0
 * https://github.com/demo/app
 */
// 参考自 https://blog.example.net/post/1
import os
const API_KEY = "sk-live-4b8f2a91c3d7e5064b8f";
const PHONE = "13800138000";


// 计算订单总价
function total(items) {
  return items.reduce((s, i) => s + i.price, 0);
}
'''

VENDOR_FILE = '/*! Copyright (c) 2019 Other Vendor Inc. MIT License */\nfunction h(a){return a*2}\n'


class SourceMaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "src").mkdir()
        (self.repo / "vendor").mkdir()
        (self.repo / "src" / "app.js").write_text(SELF_FILE, encoding="utf-8")
        (self.repo / "vendor" / "lib.js").write_text(VENDOR_FILE, encoding="utf-8")
        self.cfg = {"copyright_holder": "Demo Co.,Ltd.", "self_open_source": True,
                    "self_aliases": ["demo", "Demo Co.,Ltd."]}

    def _read(self, **kwargs):
        options = {"redact": True, "scrub": True, "tokens": _own_tokens(self.cfg),
                   "trim_comments": True, "trim_imports": True}
        options.update(kwargs)
        return generate_source_docx.read_lines(
            self.repo, ["src/app.js", "vendor/lib.js"], **options)

    def _text(self, **kwargs):
        result = self._read(**kwargs)
        lines = result[0] if isinstance(result, tuple) else result
        return "\n".join(lines)

    def test_third_party_file_never_enters_material(self):
        text = self._text()
        self.assertNotIn("Other Vendor Inc.", text)
        self.assertNotIn("function h(a)", text)

    def test_self_license_header_and_repo_url_are_removed(self):
        text = self._text()
        self.assertNotIn("Apache License", text)
        self.assertNotIn("github.com/demo/app", text)
        self.assertNotIn("Copyright (c) 2026", text)

    def test_source_attribution_comment_is_removed(self):
        self.assertNotIn("参考自", self._text())

    def test_secrets_and_pii_are_redacted_without_breaking_code(self):
        text = self._text()
        self.assertNotIn("sk-live-4b8f2a91c3d7e5064b8f", text)
        self.assertNotIn("13800138000", text)
        self.assertIn('const API_KEY = "****";', text)

    def test_business_code_survives(self):
        text = self._text()
        self.assertIn("function total(items) {", text)
        self.assertIn("items.reduce", text)

    def test_keep_comments_preserves_business_comment(self):
        self.assertIn("计算订单总价", self._text(trim_comments=False))

    def test_trim_imports_drops_import_lines(self):
        self.assertNotIn("import os", self._text())
        self.assertIn("import os", self._text(trim_imports=False))


if __name__ == "__main__":
    unittest.main()
