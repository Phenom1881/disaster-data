import csv
import io
import tempfile
import unittest
from pathlib import Path

import ms_sos_backfill as sos

LISTING = """
<h2>Governor Phil Bryant</h2>
<table><tbody>
<tr><td>1455</td><td><a href="/sites/default/files/executive-orders/1455.pdf">1455</a></td><td></td><td>12/06/2019</td></tr>
<tr><td>1291</td><td><a href="/sites/default/files/executive-orders/bryant.ex.order.1291.pdf">PDF</a></td><td></td><td>04/30/2012</td></tr>
</tbody></table>
<h2>Governor Haley Barbour</h2>
<table><tbody>
<tr><td>1069-1073</td><td><a href="/sites/default/files/executive-orders/barbour.exec.order.1069.to.1073.pdf">PDF</a></td><td></td><td>01/06/2012</td></tr>
<tr><td>1040</td><td><a href="https://www.sos.ms.gov/sites/default/files/executive-orders/barbour.exec.order.1040.pdf">PDF</a></td><td></td><td>07/23/2010</td></tr>
<tr><td>998-1002</td><td><a href="/sites/default/files/executive-orders/barbour.ex.orders.998.to.1002.pdf">All Barbour Pardons</a></td><td>All Barbour Pardons</td><td></td></tr>
</tbody></table>
<h2>Governor Tate Reeves</h2>
<table><tbody>
<tr><td>1456</td><td><a href="/sites/default/files/executive-orders/1456.pdf">PDF</a></td><td></td><td>03/04/2020</td></tr>
</tbody></table>
"""

BONNIE = ("EXECUTIVE ORDER NO. 1040 WHEREAS, Tropical Storm Bonnie is forecast to make landfall on the "
          "Mississippi Gulf Coast bringing heavy rain and high winds; WHEREAS, the Mississippi National Guard "
          "may be needed to support state and local emergency response; NOW, THEREFORE, I, Haley Barbour, "
          "Governor, do hereby authorize the Adjutant General to activate personnel. " * 2)
FLAGS = ("WHEREAS, the victims of the tornado that struck Yazoo County will be remembered; NOW THEREFORE "
         "the flags of the State shall be flown at half-staff. emergency")
EXTEND = ("WHEREAS, Executive Order 1300 declared a state of emergency for Hurricane Isaac; NOW, THEREFORE, "
          "I do hereby extend the state of emergency.")
APPOINT = "WHEREAS, the Board of Health requires a new member; NOW, THEREFORE, I appoint the following."
CLEMENCY = ("WHEREAS, in April, 2011, areas of the State of Mississippi were affected by a severe weather system "
            "which included severe thunderstorms and tornadoes; WHEREAS, the inmates listed below satisfactorily "
            "performed services for the citizens of Mississippi during the disaster; NOW, THEREFORE, the "
            "sentences of the inmates are suspended.")


def make_pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=letter)
    y = 740
    words = text.split()
    for start in range(0, len(words), 12):
        page.drawString(40, y, " ".join(words[start:start + 12]))
        y -= 14
    page.save()
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content=b"", text=""):
        self.content, self.text = content, text

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pdfs):
        self.pdfs, self.calls = pdfs, []

    def get(self, url, **_):
        self.calls.append(url)
        return FakeResponse(content=self.pdfs[url])


class ListingTests(unittest.TestCase):
    def test_rows_parse_with_dates_and_absolute_links(self):
        rows = {r["order_number"]: r for r in sos.parse_listing(LISTING)}
        self.assertEqual(rows["1291"]["date_signed"], "2012-04-30")
        self.assertEqual(rows["1291"]["pdf_url"],
                         "https://www.sos.ms.gov/sites/default/files/executive-orders/bryant.ex.order.1291.pdf")
        self.assertEqual(rows["1069"]["date_signed"], "2012-01-06")
        self.assertTrue(rows["998"]["pardons"])

    def test_only_2008_2019_orders_are_wanted(self):
        wanted = sorted(r["order_number"] for r in sos.parse_listing(LISTING) if sos.wanted(r))
        self.assertEqual(wanted, ["1040", "1069", "1291", "1455"])

    def test_governor_by_number(self):
        self.assertEqual(sos.governor_for(1289), "Haley Barbour")
        self.assertEqual(sos.governor_for(1290), "Phil Bryant")
        self.assertEqual(sos.governor_for(1456), "Tate Reeves")


class ClassifyTests(unittest.TestCase):
    def test_storm_call_out_is_weather(self):
        weather, hazards = sos.classify(BONNIE)
        self.assertTrue(weather)
        self.assertIn("tropical storm", hazards)

    def test_flags_extension_and_appointment_are_not(self):
        for text in (FLAGS, EXTEND, APPOINT, CLEMENCY):
            self.assertFalse(sos.classify(text)[0], text[:40])

    def test_storm_order_using_inmate_labor_is_still_weather(self):
        text = BONNIE + " State agencies, including inmate work crews, shall assist with debris removal."
        self.assertTrue(sos.classify(text)[0])

    def test_summary_is_first_whereas_clause(self):
        self.assertTrue(sos.summarize(BONNIE).startswith("Tropical Storm Bonnie is forecast"))

    def test_summary_survives_ocr_spellings_of_whereas(self):
        text = "STATE OF MISSISSIPPI EXECUTIVE ORDER NO. 1040 WI:IEREAS, the State is expecting a storm; NOW"
        self.assertEqual(sos.summarize(text), "the State is expecting a storm")


class RunTests(unittest.TestCase):
    def test_run_reads_new_orders_once_and_adds_weather_rows(self):
        base = "https://www.sos.ms.gov/sites/default/files/executive-orders/"
        pdfs = {base + "barbour.exec.order.1040.pdf": make_pdf(BONNIE),
                base + "barbour.exec.order.1069.to.1073.pdf": make_pdf(APPOINT * 6),
                base + "bryant.ex.order.1291.pdf": make_pdf(FLAGS * 3),
                base + "1455.pdf": make_pdf(EXTEND * 4)}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = root / "declarations_for_join.csv"
            sos.write_csv(join, sos.JOIN_FIELDS, [{"declaration_id": "MS-EO-1592", "governor": "Tate Reeves",
                                                   "eo_number": "1592", "event_description": "x",
                                                   "date_signed": "2026-01-22", "archive_record_url": "u"}])
            session = FakeSession(pdfs)
            stats = sos.run(root / "cache.csv", join, session=session, listing_html=LISTING)
            self.assertEqual((stats["listed"], stats["read"], stats["weather"], stats["added"]), (4, 4, 1, 1))
            with join.open(encoding="utf-8") as handle:
                rows = {r["declaration_id"]: r for r in csv.DictReader(handle)}
            self.assertIn("MS-EO-1592", rows)
            bonnie = rows["MS-EO-1040"]
            self.assertEqual((bonnie["date_signed"], bonnie["governor"]), ("2010-07-23", "Haley Barbour"))
            self.assertIn("Hazards named in the order: tropical storm", bonnie["event_description"])
            again = FakeSession(pdfs)
            stats = sos.run(root / "cache.csv", join, session=again, listing_html=LISTING)
            self.assertEqual((stats["read"], again.calls), (0, []))

    def test_weather_rows_from_an_older_classifier_are_read_again(self):
        url = "https://www.sos.ms.gov/sites/default/files/executive-orders/bryant.ex.order.1291.pdf"
        old = {"order_number": "1291", "governor": "Phil Bryant", "date_signed": "2012-04-30", "pdf_url": url,
               "text_source": "ocr", "weather_declaration": "true", "hazards": "tornadoes", "summary": "s",
               "checked_on": "2026-10-06", "classifier": ""}
        listing = '<table><tr><td>1291</td><td><a href="%s">PDF</a></td><td></td><td>04/30/2012</td></tr></table>' % url
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sos.write_csv(root / "cache.csv", sos.CACHE_FIELDS, [old])
            sos.write_csv(root / "j.csv", sos.JOIN_FIELDS, [])
            session = FakeSession({url: make_pdf(CLEMENCY * 2)})
            stats = sos.run(root / "cache.csv", root / "j.csv", session=session, listing_html=listing)
            self.assertEqual((stats["read"], stats["weather"], stats["added"]), (1, 0, 0))
            again = FakeSession({})
            self.assertEqual(sos.run(root / "cache.csv", root / "j.csv", session=again,
                                     listing_html=listing)["read"], 0)

    def test_hand_saved_rows_are_left_alone(self):
        cache = [{"order_number": "1036", "governor": "Haley Barbour", "date_signed": "2010-04-24",
                  "pdf_url": "u", "weather_declaration": "true", "hazards": "tornadoes", "summary": "s"}]
        with tempfile.TemporaryDirectory() as tmp:
            join = Path(tmp) / "j.csv"
            sos.write_csv(join, sos.JOIN_FIELDS, [])
            self.assertEqual(sos.add_to_join(join, cache, skip_ids=["MS-EO-1036"]), 0)

    def test_listing_failure_keeps_cached_rows(self):
        class Broken:
            def get(self, *_, **__):
                raise sos.requests.ConnectionError("refused")
        cache_row = {"order_number": "1040", "governor": "Haley Barbour", "date_signed": "2010-07-23",
                     "pdf_url": "u", "text_source": "text", "weather_declaration": "true",
                     "hazards": "tropical storm", "summary": "Bonnie", "checked_on": "2026-10-06"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sos.write_csv(root / "cache.csv", sos.CACHE_FIELDS, [cache_row])
            sos.write_csv(root / "j.csv", sos.JOIN_FIELDS, [])
            stats = sos.run(root / "cache.csv", root / "j.csv", session=Broken())
            self.assertTrue(stats["listing_error"])
            self.assertEqual(stats["added"], 1)


if __name__ == "__main__":
    unittest.main()
