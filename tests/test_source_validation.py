import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
try:
    from reportlab.pdfgen import canvas
except ImportError:  # 可选依赖，未安装时跳过本文件
    canvas = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_validation import SourceValidationError, parse_source_html, validate_source_pdf


class SourceHTMLValidationTests(unittest.TestCase):
    def test_preserves_decoded_code_and_intentional_blank_rows(self):
        html = '''<!doctype html><html><head><style>.source-page { display: block; }</style></head>
        <body><section class="print source-page"><div class="source-line">  if (a &lt; b &amp;&amp; b &gt; 0) {</div>
        <div class="source-line">&nbsp;</div><div class="source-line">    return "中文 &lt;div&gt;";</div>
        <div class="source-line">}</div></section>
        <section class="source-page"><div class="source-line">const literal = "&amp;nbsp;";</div></section></body></html>'''
        self.assertEqual(parse_source_html(html), [
            ['  if (a < b && b > 0) {', '\xa0', '    return "中文 <div>";', '}'],
            ['const literal = "&nbsp;";'],
        ])

    def test_rejects_missing_empty_and_whitespace_only_pages(self):
        cases = [
            "<html><body>Not source material</body></html>",
            '<section class="source-page"></section>',
            '<section class="source-page"><div class="source-line">&nbsp; \t&#160;</div></section>',
            '<section class="source-page"><div class="source-line">const ok = true;</div></section>'
            '<section class="source-page"><div class="source-line">&nbsp;</div></section>',
        ]
        for html in cases:
            with self.subTest(html=html), self.assertRaises(SourceValidationError):
                parse_source_html(html)

    def test_rejects_old_sixty_page_padding_output(self):
        page = '<section class="source-page">' + '<div class="source-line">&nbsp;</div>' * 90 + '</section>'
        with self.assertRaisesRegex(SourceValidationError, "第 1 页为空白"):
            parse_source_html(page * 60)

    def test_rejects_malformed_source_structure(self):
        cases = [
            '<div class="source-line">const x = 1;</div>',
            '<div class="source-page"><div class="source-line">const x = 1;</div></div>',
            '<section class="source-page"><div class="source-line">const x = 1;</section>',
            '<section class="source-page"><div class="source-line">const x = 1;</div>',
            '<section class="source-page"><section class="source-page"></section></section>',
            '<section class="source-page"><div class="source-line"><script>alert(1)</script></div></section>',
        ]
        for html in cases:
            with self.subTest(html=html), self.assertRaises(SourceValidationError):
                parse_source_html(html)


@unittest.skipIf(canvas is None, "未安装 reportlab（可选依赖）")
class SourcePDFValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_pdf(self, pages, name="source.pdf"):
        path = self.root / name
        document = canvas.Canvas(str(path))
        for rows in pages:
            for index, row in enumerate(rows):
                document.drawString(50, 780 - index * 16, row)
            document.showPage()
        document.save()
        return path

    def make_unicode_pdf(self, pages):
        # Model the Unicode mappings emitted by a browser's PDF font subset.
        # An explicit CMap exercises real pypdf extraction without relying on
        # which Unicode ligature glyphs the host's installed fonts contain.
        characters = sorted(set("".join(row for rows in pages for row in rows)))
        codes = {char: index for index, char in enumerate(characters, 1)}
        mappings = "\n".join(f"<{code:02x}> <{char.encode('utf-16-be').hex()}>" for char, code in codes.items())
        cmap = DecodedStreamObject()
        cmap.set_data(("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
                       "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
                       "/CMapName /SourceValidation def\n/CMapType 2 def\n"
                       "1 begincodespacerange\n<00> <ff>\nendcodespacerange\n"
                       f"{len(codes)} beginbfchar\n{mappings}\nendbfchar\n"
                       "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend").encode("ascii"))
        writer = PdfWriter()
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/ToUnicode"): writer._add_object(cmap),
        })
        font_ref = writer._add_object(font)
        for rows in pages:
            page = writer.add_blank_page(width=595, height=842)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
            })
            stream = DecodedStreamObject()
            commands = []
            for index, row in enumerate(rows):
                encoded = "".join(f"{codes[char]:02x}" for char in row)
                commands.append(f"BT /F1 12 Tf 50 {780 - index * 16} Td <{encoded}> Tj ET")
            stream.set_data("\n".join(commands).encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
        path = self.root / "unicode.pdf"
        writer.write(path)
        return path

    def test_valid_pdf_and_exact_code_match_ignoring_whitespace(self):
        pages = [["function run() {", "  return 42;", "}"], ["const ok = a < b && b > 0;"]]
        path = self.make_pdf(pages)
        self.assertEqual(validate_source_pdf(path, expected_pages=pages, expected_count=2),
                         {"pages": 2, "nonblank_pages": 2})
        self.assertEqual(validate_source_pdf(path, expected_pages=[['function run(){return 42;}'], pages[1]])["pages"], 2)

    def test_pdf_typographic_ligatures_match_source_without_hiding_changed_letters(self):
        rendered = 'const suﬃx = Conﬁg; const forms = "ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ";'
        source = 'const suffix = Config; const forms = "ff fi fl ffi ffl st st";'
        path = self.make_unicode_pdf([["1", rendered]])
        self.assertIn(rendered, PdfReader(path).pages[0].extract_text())
        self.assertEqual(validate_source_pdf(path, expected_pages=[[source]])["pages"], 1)
        for changed in [source.replace("suffix", "sufix"), source.replace("Config", "Confg")]:
            with self.subTest(changed=changed), self.assertRaisesRegex(SourceValidationError, "与 HTML 源码不一致"):
                validate_source_pdf(path, expected_pages=[[changed]])

    def test_does_not_normalize_other_unicode_source_characters(self):
        for rendered, expected in [('const Ｃ = 1;', 'const C = 1;'), ('const x = "①";', 'const x = "1";')]:
            path = self.make_unicode_pdf([[rendered]])
            self.assertIn(rendered, PdfReader(path).pages[0].extract_text())
            with self.subTest(rendered=rendered), self.assertRaisesRegex(SourceValidationError, "与 HTML 源码不一致"):
                validate_source_pdf(path, expected_pages=[[expected]])

    def test_rejects_sixty_blank_pages(self):
        path = self.root / "blank.pdf"
        writer = PdfWriter()
        for _ in range(60):
            writer.add_blank_page(width=595, height=842)
        writer.write(path)
        with self.assertRaisesRegex(SourceValidationError, "第 1 页为空白"):
            validate_source_pdf(path, expected_count=60)

    def test_rejects_page_number_only(self):
        for counter in ["1", " 1 ", "1 / 60", "Page 1 of 60"]:
            with self.subTest(counter=counter), self.assertRaisesRegex(SourceValidationError, "只有页码"):
                validate_source_pdf(self.make_pdf([[counter]]))

    def test_rejects_any_blank_page(self):
        path = self.make_pdf([["const first = 1;"], [], ["const last = 3;"]])
        with self.assertRaisesRegex(SourceValidationError, "第 2 页为空白"):
            validate_source_pdf(path)

    def test_allows_exact_page_counter_on_either_edge(self):
        pages = [["const first = 1;"], ["const second = 2;"]]
        path = self.make_pdf([["1", *pages[0]], [*pages[1], "2"]])
        self.assertEqual(validate_source_pdf(path, expected_pages=pages)["nonblank_pages"], 2)

    def test_required_page_numbers_are_checked_on_every_page(self):
        pages = [["const first = 1;"], ["const second = 2;"]]
        valid = self.make_pdf([["1", *pages[0]], ["2", *pages[1]]])
        self.assertEqual(validate_source_pdf(valid, expected_pages=pages, require_page_numbers=True)["pages"], 2)
        for last in [pages[1], ["1", *pages[1]]]:
            path = self.make_pdf([["1", *pages[0]], last])
            with self.assertRaisesRegex(SourceValidationError, "第 2 页缺少正确页码"):
                validate_source_pdf(path, expected_pages=pages, require_page_numbers=True)

    def test_does_not_strip_source_digits_or_wrong_counter(self):
        for rows in [["1const x = 1;"], ["const x = 1;1"], ["2", "const x = 1;"], ["Page 1", "const x = 1;"]]:
            with self.subTest(rows=rows), self.assertRaisesRegex(SourceValidationError, "与 HTML 源码不一致"):
                validate_source_pdf(self.make_pdf([rows]), expected_pages=[["const x = 1;"]])
        pages = [["1 + value;", "const x = 1;"]]
        self.assertEqual(validate_source_pdf(self.make_pdf(pages), expected_pages=pages)["pages"], 1)

    def test_rejects_changed_truncated_extra_or_wrong_page_text(self):
        expected = [["function run() {", "return 42;", "}"]]
        variants = [["function run() {", "return 41;", "}"], ["function run() {"],
                    [*expected[0], "unexpected();"]]
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaisesRegex(SourceValidationError, "与 HTML 源码不一致"):
                validate_source_pdf(self.make_pdf([rows]), expected_pages=expected)
        path = self.make_pdf([["const b = 2;"], ["const a = 1;"]])
        with self.assertRaisesRegex(SourceValidationError, "第 1 页与 HTML"):
            validate_source_pdf(path, expected_pages=[["const a = 1;"], ["const b = 2;"]])

    def test_rejects_wrong_page_count_and_invalid_expectations(self):
        path = self.make_pdf([["const x = 1;"]])
        for kwargs in [{"expected_count": 2}, {"expected_pages": [["const x = 1;"], ["const y = 2;"]]},
                       {"expected_count": 0}, {"expected_count": -1}, {"expected_count": 1.5},
                       {"expected_pages": []}, {"expected_pages": [["  ", "\xa0"]]},
                       {"expected_pages": [["const x = 1;"]], "expected_count": 2}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(SourceValidationError):
                validate_source_pdf(path, **kwargs)

    def test_rejects_corrupt_missing_encrypted_and_zero_page_pdf(self):
        corrupt = self.root / "corrupt.pdf"
        corrupt.write_bytes(b"not a PDF")
        zero = self.root / "zero.pdf"
        PdfWriter().write(zero)
        valid = self.make_pdf([["const secret = 1;"]])
        encrypted = self.root / "encrypted.pdf"
        writer = PdfWriter()
        writer.add_page(PdfReader(valid).pages[0])
        writer.encrypt("password")
        writer.write(encrypted)
        for path in [corrupt, self.root / "missing.pdf", zero, encrypted]:
            with self.subTest(path=path.name), self.assertRaises(SourceValidationError):
                validate_source_pdf(path)


if __name__ == "__main__":
    unittest.main()
