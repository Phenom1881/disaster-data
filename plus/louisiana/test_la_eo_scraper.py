import csv, tempfile, unittest
import la_eo_scraper as la

FIXTURE='''<a href="/media/a.pdf">JBE 21-10 State of Emergency--Hurricane Ida</a><a href="/media/b.pdf">JBE 21-11 Renewal of State of Emergency--Hurricane Ida</a>'''

class LouisianaTests(unittest.TestCase):
    def test_index_and_modifier_exclusion(self):
        actions=la.parse_index(FIXTURE,la.ARCHIVE_URL)
        self.assertEqual(actions[0].number,"JBE 21-10")
        enriched=[la.Action(a.number,a.description,a.url,"2021-08-26",a.description) for a in actions]
        with tempfile.TemporaryDirectory() as root:
            paths=[root+f"/{n}.csv" for n in ("actions","rels","join")]; la.write_outputs(enriched,*paths)
            with open(paths[2],encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(list(rows[0]),list(la.JOIN_FIELDS)); self.assertEqual(len(rows),1)
    def test_no_overrides(self): self.assertEqual(la.HAZARD_OVERRIDES,{})
    def test_untitled_renewal_detected_from_official_text(self):
        action=la.Action("JML 24-147","State of Emergency Hurricane Francine","u","2024-09-18","Governor declared a state of emergency on September 9, 2024, in JML 24-142")
        self.assertEqual(la.classify(action),"extension")

if __name__=="__main__": unittest.main()


class DocumentDateTests(unittest.TestCase):
    """2026-09-28: scanned PDFs are read with OCR and saved dates are kept."""

    @unittest.skipUnless(la.TESSERACT, "tesseract is not installed")
    def test_scanned_pdf_is_read_with_ocr(self):
        import io
        from PIL import Image, ImageDraw, ImageFont
        page = Image.new("L", (1700, 2200), 255)
        draw = ImageDraw.Draw(page)
        try:
            font = ImageFont.truetype("DejaVuSerif.ttf", 30)
        except OSError:
            font = ImageFont.load_default(size=30)
        for i, line in enumerate(["EXECUTIVE ORDER NUMBER JML 24-89", "STATE OF EMERGENCY SEVERE STORMS AND TORNADOES",
                                  "IN WITNESS WHEREOF, I have set my hand", "this 5th day of June, 2024."]):
            draw.text((200, 200 + i * 60), line, font=font, fill=0)
        out = io.BytesIO(); page.save(out, "PDF", resolution=200)
        self.assertEqual(la.extract_date(la._pdf_text(out.getvalue())), "2024-06-05")

    def test_saved_dates_are_loaded(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.csv")
            with open(path, "w") as handle:
                handle.write("eo_number,date_signed\nJML 24-72,2024-05-20\nJML 24-89,\n")
            self.assertEqual(la.load_saved_dates(path), {"JML 24-72": "2024-05-20"})
