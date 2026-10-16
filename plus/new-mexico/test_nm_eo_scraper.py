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


class ReviewedDateTests(unittest.TestCase):
    """Weather declarations whose signing date OCR cannot read get the date
    read by eye from the signed order, so they reach the join."""
    # Shaped like the real OCR of EO 2020-077: the event dates sit in a WHEREAS
    # clause far above the signature block, and OCR reads the typed "5TH" as "STH".
    SIGNATURE = ("EXECUTIVE ORDER {n}\nDECLARING A DISASTER DUE TO FLOODING\n"
                 "WHEREAS, from July 24, 2020 to July 26, 2020 monsoon rain caused flooding in the Village of Williamsburg;\n"
                 "WHEREAS, the flooding damaged roads, culverts, water and wastewater systems and other public property;\n"
                 "WHEREAS, the cost of repairs is beyond the means of the local government;\n"
                 "NOW, THEREFORE, I, Michelle Lujan Grisham, Governor of the State of New Mexico, declare a disaster "
                 "and direct the Department of Homeland Security and Emergency Management to make available its resources.\n"
                 "THIS ORDER supersedes any other previous orders, proclamations, or directives in conflict. This Executive "
                 "Order shall take effect immediately and shall remain in effect until such time as the Governor rescinds it.\n\n"
                 "ATTEST: DONE AT THE EXECUTIVE OFFICE\n' 2 THIS STH DAY OF NOVEMBER 2020\n"
                 "MAGGIE TOULOUSE OLIVER WITNESS MY HAND AND THE GREAT\nSECRETARY OF STATE SEAL OF THE STATE OF NEW MEXICO\n")

    def parse(self, number):
        cache = {number: {"text": self.SIGNATURE.format(n=number), "via_ocr": "true"}}
        return nm.parse_document(number, "u", cache)

    def test_a_reviewed_date_fills_a_signature_ocr_cannot_read(self):
        self.assertEqual(nm.extract_date(self.SIGNATURE.format(n="2020-077"), "2020-077"), "")   # "STH" is not a day
        self.assertEqual(self.parse("2020-077").date, "2020-11-05")
        self.assertEqual(self.parse("2020-076").date, "")                                        # not reviewed: no guess

    def test_a_reviewed_date_wins_over_a_misread_one(self):
        # The 2019 days are handwritten; OCR that reads "7 DAY" must not beat the date checked by eye.
        text = self.SIGNATURE.format(n="2019-008").replace("STH DAY OF NOVEMBER 2020", "7 DAY OF APRIL 2019")
        self.assertEqual(nm.extract_date(text, "2019-008"), "2019-04-07")
        self.assertEqual(nm.signing_date(text, "2019-008"), "2019-04-22")

    def test_a_fresh_download_uses_the_reviewed_date_too(self):
        class Pdf: content = b"%PDF-1.4 scan"
        get, extract_pdf = nm.get, nm.extract_pdf
        nm.get = lambda url: Pdf()
        nm.extract_pdf = lambda content: (self.SIGNATURE.format(n="2020-077"), True, True)
        try:
            action = nm.parse_document("2020-077", "u")
        finally:
            nm.get, nm.extract_pdf = get, extract_pdf
        self.assertEqual(action.date, "2020-11-05")
        self.assertEqual(nm.classify(action), "declaration")

    def test_a_reviewed_declaration_reaches_the_join(self):
        action = self.parse("2020-077")
        with tempfile.TemporaryDirectory() as root:
            paths = [root + "/" + name for name in ("actions.csv", "rels.csv", "join.csv")]
            nm.write_outputs([action], *paths)
            with open(paths[2], encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual([(r["declaration_id"], r["date_signed"]) for r in rows], [("NM-2020-077", "2020-11-05")])

    def test_reviewed_dates_are_well_formed(self):
        from datetime import datetime
        for number, day in nm.REVIEWED_DATES.items():
            self.assertRegex(number, r"^20\d{2}-\d{3}$")
            self.assertEqual(datetime.strptime(day, "%Y-%m-%d").year, int(number[:4]))

