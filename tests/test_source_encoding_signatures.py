import codecs
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_encoding import SourceEncodingError, decode_bytes  # noqa: E402
from source_material import strip_signatures  # noqa: E402
from source_material_render import read_lines  # noqa: E402

CODE = "const title = '订单管理';\nfunction save() { return title }\n"


class DecodeTests(unittest.TestCase):
    def test_utf8_gbk_and_utf16_are_decoded_correctly(self):
        for data, name in [(CODE.encode("utf-8"), "utf-8"), (CODE.encode("gbk"), "gb18030"),
                           (codecs.BOM_UTF8 + CODE.encode("utf-8"), "utf-8-sig"),
                           (CODE.encode("utf-16"), "utf-16"), (CODE.encode("utf-16-le"), "utf-16-le")]:
            text, encoding = decode_bytes(data)
            self.assertEqual(text, CODE, name)
            self.assertEqual(encoding, name)

    def test_binary_and_undecodable_files_are_rejected(self):
        for data in (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", bytes(range(128, 256)) * 3,
                     "abc".encode("utf-8") + b"\xff\xfe\xfd\xfc" * 10):
            with self.assertRaises(SourceEncodingError):
                decode_bytes(data)


class SignatureTests(unittest.TestCase):
    def test_personal_signatures_and_copyright_lines_are_removed(self):
        lines = ["/**", " * @author zhangsan", " * @since 2024-01-01", " * Created by lisi on 2024/1/1.",
                 "// 作者：王五", "# Author: someone", " * Copyright (c) 2024 本公司", "<!-- 版权所有 -->",
                 " */", "public class OrderService {", '    String author = "admin";',
                 "    // 计算订单总价", "}"]
        kept, removed = strip_signatures(lines)
        self.assertEqual(removed, 7)
        self.assertIn('    String author = "admin";', kept)  # 业务代码里的 author 变量不动
        self.assertIn("    // 计算订单总价", kept)              # 普通注释不动
        self.assertIn("public class OrderService {", kept)


class ReadLinesTests(unittest.TestCase):
    def test_extraction_decodes_gbk_drops_garbled_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            # 署名放在代码中间：文件头注释块由原有的文件头清理处理，这里测新的署名清理
            (repo / "gbk.js").write_bytes((CODE + "/**\n * @author 张三\n */\n" + CODE).encode("gbk"))
            (repo / "broken.js").write_bytes(b"abc" + b"\xff\xfe\xfd\xfc" * 20)
            (repo / "vendor_like.js").write_text(CODE * 30 + "// Copyright (c) 2020 Other Corp\n" + CODE,
                                                 encoding="utf-8")
            lines, missing, skipped, stats = read_lines(
                repo, ["gbk.js", "broken.js", "vendor_like.js"], redact=False, tokens=("本公司",),
                trim_comments=False, trim_imports=False, max_blank_lines=0)
        self.assertIn("const title = '订单管理';", lines)               # GBK 中文正确
        self.assertFalse(any("@author" in line for line in lines))       # 保留注释时也清掉署名
        reasons = dict(skipped)
        self.assertIn("编码有问题", reasons["broken.js"])
        self.assertIn("他人版权声明", reasons["vendor_like.js"])         # 文件中间的他人版权也排除
        self.assertEqual(stats["encoding_skipped"], 1)
        self.assertEqual(stats["signatures"], 1)


if __name__ == "__main__":
    unittest.main()
