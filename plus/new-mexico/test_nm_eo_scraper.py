import csv
import tempfile
import unittest
import nm_eo_scraper as nm

TEXT = """STATE OF NEW MEXICO EXECUTIVE ORDER 2024-100 DECLARING A STATE OF EMERGENCY DUE TO SEVERE STORMS AND FLOODING WHEREAS heavy rainfall caused flooding; I hereby declare a state of emergency. Signed this 20th day of June, 2024."""

class NewMexicoTests(unittest.TestCase):
    def test_index(self):
        rows = nm.parse_index('<a href="/files/a.pdf">Executive Order 2024-100</a>', nm.ARCHIVE_URL)
        self.assertEqual(rows[0][0], "2024-100")

    def test_date_title_and_classification(self):
        action = nm.Action("2024-100", nm.extract_title(TEXT, "2024-100"), nm.extract_date(TEXT, "2024-100"), "https://example.gov/a.pdf", TEXT)
        self.assertEqual(action.date, "2024-06-20")
        self.assertEqual(nm.classify(action), "declaration")

    def test_modifier_excluded_from_join(self):
        original = nm.Action("2024-100", "Declaring a State of Emergency Due to Severe Storms and Flooding", "2024-06-20", "https://example.gov/a.pdf", TEXT)
        renewal = nm.Action("2024-101", "Renewing the State of Emergency Due to Severe Storms and Flooding", "2024-07-20", "https://example.gov/b.pdf", TEXT)
        with tempfile.TemporaryDirectory() as root:
            paths = [root + "/" + name for name in ("actions.csv", "rels.csv", "join.csv")]
            nm.write_outputs([original, renewal], *paths)
            with open(paths[2], encoding="utf-8") as handle: rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(tuple(rows[0]), nm.JOIN_FIELDS)

    def test_no_overrides(self):
        self.assertEqual(nm.HAZARD_OVERRIDES, {})

    def test_scan_is_unclassified(self):
        action = nm.Action("2024-999", "Executive Order 2024-999 (text unavailable)", "", "https://example.gov/scan.pdf", "", False, True)
        self.assertEqual(nm.classify(action), "unclassified")

if __name__ == "__main__": unittest.main()


# ---------------------------------------------------------------- 2026-09-28
# OCR through the tesseract program, and the text cache between runs.
import io as _io
import os as _os


def _scan(lines, dpi=200):
    from PIL import Image, ImageDraw, ImageFont
    page = Image.new("L", (int(8.5 * dpi), int(11 * dpi)), 255)
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype("DejaVuSerif.ttf", int(dpi * 0.14))
    except OSError:
        font = ImageFont.load_default(size=int(dpi * 0.14))
    for i, line in enumerate(lines):
        draw.text((dpi, dpi + i * int(dpi * 0.28)), line, font=font, fill=0)
    out = _io.BytesIO()
    page.rotate(0.4, fillcolor=255).save(out, "PDF", resolution=dpi)
    return out.getvalue()


ORDER = ["STATE OF NEW MEXICO", "EXECUTIVE ORDER 2025-104",
         "DECLARING A STATE OF EMERGENCY DUE TO SEVERE FLOODING IN LINCOLN COUNTY",
         "WHEREAS, severe flooding began on June 17, 2025;", "",
         "DONE AT THE EXECUTIVE OFFICE THIS 19TH DAY OF JUNE 2025.",
         "WITNESS MY HAND AND THE GREAT SEAL OF THE STATE OF NEW MEXICO."]


class OcrAndCacheTests(unittest.TestCase):
    @unittest.skipUnless(nm.TESSERACT, "tesseract is not installed")
    def test_scanned_order_is_read_classified_and_joined(self):
        text, ok, via_ocr = nm.extract_pdf(_scan(ORDER))
        self.assertTrue(ok and via_ocr)
        action = nm.Action("2025-104", nm.extract_title(text, "2025-104"), nm.extract_date(text, "2025-104"),
                           "u", text, True, True, True)
        self.assertTrue(action.title.upper().startswith("DECLARING A STATE OF EMERGENCY"), action.title)
        self.assertEqual(action.date, "2025-06-19")
        self.assertEqual(nm.classify(action), "declaration")

    def test_cached_text_is_used_without_downloading(self):
        text = "EXECUTIVE ORDER 2025-104 DECLARING A STATE OF EMERGENCY DUE TO FLOODING WHEREAS x " + "y " * 3000 + \
               "DONE THIS 19TH DAY OF JUNE 2025. WITNESS MY HAND"
        original = nm.get
        nm.get = lambda url: (_ for _ in ()).throw(AssertionError("downloaded"))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = _os.path.join(tmp, nm.CACHE_NAME)
                nm.write_cache(path, [nm.Action("2025-104", "t", "", "u", text, True, True, True)])
                action = nm.parse_document("2025-104", "u", nm.load_cache(path))
        finally:
            nm.get = original
        self.assertEqual(action.date, "2025-06-19")          # the attestation survives trimming
        self.assertEqual(nm.classify(action), "declaration")
        self.assertTrue(action.via_ocr)
