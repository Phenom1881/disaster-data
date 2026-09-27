"""Tests for or_eo_scraper.py. Offline: the order list and PDFs are fakes,
and the scanned orders are drawn here. The OCR tests need the tesseract
program and are skipped without it.

    cd plus/oregon && python -m unittest test_or_eo_scraper
"""
import csv
import io
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

import requests

import or_eo_scraper as ore

TODAY = date(2026, 9, 27)
CONFLAGRATION = "Invocation of Emergency Conflagration Act for the Wrights Spring Fire in Klamath County"


def scanned_order(lines, dpi=200, seed=1):
    """An image-only PDF, like Oregon's: a page drawn as a picture with
    scanner speckle and a slight tilt, and no text layer."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    random.seed(seed)
    width, height = int(8.5 * dpi), int(11 * dpi)
    page = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype("DejaVuSerif.ttf", int(dpi * 0.16))
    except OSError:
        font = ImageFont.load_default(size=int(dpi * 0.16))
    y = dpi
    for line in lines:
        draw.text((dpi, y), line, font=font, fill=0)
        y += int(dpi * 0.3)
    draw.line([(dpi + i * 6, y + random.randint(-25, 25)) for i in range(60)], fill=0, width=3)
    page = page.rotate(0.6, fillcolor=255, resample=Image.BICUBIC)
    pixels = page.load()
    for _ in range(int(width * height * 0.02)):
        pixels[random.randrange(width), random.randrange(height)] = random.choice((0, 90, 160))
    page = page.filter(ImageFilter.GaussianBlur(0.6)).convert("1").convert("L")
    out = io.BytesIO()
    page.save(out, "PDF", resolution=dpi)
    return out.getvalue()


SIGNED_ORDER = [
    "EXECUTIVE ORDER NO. 26-24",
    "INVOCATION OF THE EMERGENCY CONFLAGRATION ACT",
    "This order remains in effect until the 30th day of September, 2026,",
    "unless rescinded sooner.",
    "",
    "Done at Salem, Oregon, this 7th day of August, 2026.",
    "", "", "Tina Kotek", "GOVERNOR", "", "ATTEST:", "", "Tobias Read", "SECRETARY OF STATE",
]


class FakeResponse:
    def __init__(self, status=200, content=b"", payload=None):
        self.status_code, self.content, self.payload = status, content, payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class FakeSession:
    def __init__(self, items, pdfs):
        self.items, self.pdfs, self.fetched = items, pdfs, []

    def get(self, url, params=None, headers=None, timeout=None):
        if url == ore.API:
            return FakeResponse(payload={"d": {"results": self.items}})
        self.fetched.append(url)
        pdf = self.pdfs.get(url)
        return FakeResponse(503) if pdf is None else FakeResponse(content=pdf)


def list_item(number, description=CONFLAGRATION, year=2026):
    return {"Document_x0020_Description": description, "Year": year, "Number": number,
            "Created": "2026-08-07T22:03:19Z",
            "File": {"ServerRelativeUrl": f"/gov/eo/eo-{year % 100:02d}-{number:02d}.pdf"}}


def url(number, year=2026):
    return f"https://www.oregon.gov/gov/eo/eo-{year % 100:02d}-{number:02d}.pdf"


def run(session, **kwargs):
    log = io.StringIO()
    with redirect_stdout(log):
        actions = ore.collect(session, today=TODAY, **kwargs)
    return actions, log.getvalue()


class ClassifyTests(unittest.TestCase):
    def action(self, description="Determination of State of Emergency due to a Severe Winter Storm"):
        return ore.Action(2024, "5", description, "https://www.oregon.gov/gov/eo/eo-24-05.pdf", signed="2024-01-12")

    def test_original(self):
        self.assertEqual(ore.classify(self.action()), "declaration")

    def test_extension(self):
        self.assertEqual(ore.classify(self.action("Extending Executive Order 24-05")), "extension")

    def test_join_excludes_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ore.write_outputs([self.action(), self.action("Extending Executive Order 24-05")],
                              root / "a.csv", root / "r.csv", root / "j.csv")
            with (root / "j.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(tuple(rows[0]), ore.JOIN_FIELDS)
            self.assertEqual(len(rows), 1)


class SigningDateTests(unittest.TestCase):
    def find(self, text, year=2026):
        return ore.find_signing_date(text, year, TODAY)

    def test_text_layer_signing_line(self):
        self.assertEqual(self.find("DONE AT SALEM THIS 12th day of January, 2024", 2024), "2024-01-12")

    def test_common_ocr_misreadings(self):
        self.assertEqual(self.find("Done at Salem, Oregon, this lst day ot Auqust, 2O26."), "2026-08-01")
        self.assertEqual(self.find("Done at Salem, Oregon, this 7t h clay of Septernber, 2026"), "2026-09-07")

    def test_signing_line_wins_over_other_dates(self):
        text = ("This order remains in effect until the 30th day of September, 2026. "
                "Done at Salem, Oregon, this 7th day of August, 2026.")
        self.assertEqual(self.find(text), "2026-08-07")

    def test_last_date_when_there_is_no_signing_line(self):
        self.assertEqual(self.find("from the 3rd day of August, 2026 to the 9th day of August, 2026"),
                         "2026-08-09")

    def test_month_first_signing_line(self):
        self.assertEqual(self.find("Done at Salem, Oregon, on August 7, 2026."), "2026-08-07")

    def test_dates_outside_the_order_year_or_in_the_future_are_refused(self):
        self.assertEqual(self.find("Done at Salem, Oregon, this 7th day of August, 2026.", 2025), "")
        self.assertEqual(self.find("Done at Salem, Oregon, this 7th day of December, 2026."), "")

    def test_no_date(self):
        self.assertEqual(self.find(CONFLAGRATION), "")


class SavedDateTests(unittest.TestCase):
    def test_saved_dates_are_loaded_with_their_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "saved.csv"
            path.write_text("declaration_id,date_signed,date_source\n"
                            "OR-EO-26-24,2026-08-07,order scan (OCR)\n"
                            "OR-EO-26-23,,\n", encoding="utf-8")
            self.assertEqual(ore.load_saved_dates(path), {"OR-EO-26-24": ("2026-08-07", "order scan (OCR)")})
            old = Path(tmp) / "old.csv"
            old.write_text("declaration_id,date_signed\nOR-EO-06-11,2006-07-04\n", encoding="utf-8")
            self.assertEqual(ore.load_saved_dates(old), {"OR-EO-06-11": ("2006-07-04", "")})
            self.assertEqual(ore.load_saved_dates(Path(tmp) / "missing.csv"), {})

    def test_a_saved_date_is_reused_without_downloading_the_pdf(self):
        session = FakeSession([list_item(24)], {})
        [action], log = run(session, saved={"OR-EO-26-24": ("2026-08-07", ore.DATE_FROM_OCR)})
        self.assertEqual(session.fetched, [])
        self.assertEqual((action.signed, action.date_source), ("2026-08-07", ore.DATE_FROM_OCR))
        self.assertIn("1 kept from earlier runs", log)

    def test_a_saved_date_from_another_year_is_read_again(self):
        session = FakeSession([list_item(24)], {url(24): b"not a pdf"})
        [action], _ = run(session, saved={"OR-EO-26-24": ("2025-08-07", ore.DATE_FROM_OCR)})
        self.assertEqual(session.fetched, [url(24)])
        self.assertEqual(action.signed, "")

    def test_administrative_orders_are_not_downloaded(self):
        session = FakeSession([list_item(26, "Establishing Responsible Artificial Intelligence Procurement Standards")], {})
        run(session)
        self.assertEqual(session.fetched, [])

    def test_an_order_listed_twice_is_downloaded_once(self):
        session = FakeSession([list_item(24), list_item(24)], {url(24): b"not a pdf"})
        run(session)
        self.assertEqual(session.fetched, [url(24)])


class WithoutOcrTests(unittest.TestCase):
    def setUp(self):
        self.saved_tesseract, ore.TESSERACT = ore.TESSERACT, None

    def tearDown(self):
        ore.TESSERACT = self.saved_tesseract

    def test_scanned_order_without_ocr_is_listed_for_review(self):
        session = FakeSession([list_item(24)], {url(24): scanned_order(SIGNED_ORDER)})
        actions, log = run(session)
        self.assertEqual(actions[0].date_note, "no_ocr")
        self.assertIn("1 not tried because OCR is not installed", log)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ore.write_outputs(actions, root / "a.csv", root / "r.csv", root / "j.csv", root / "review.csv")
            with (root / "review.csv").open() as handle:
                [row] = list(csv.DictReader(handle))
            self.assertEqual(row["declaration_id"], "OR-EO-26-24")
            self.assertIn("OCR was not available", row["review_reason"])
            with (root / "j.csv").open() as handle:
                self.assertEqual(list(csv.DictReader(handle))[0]["date_signed"], "")

    def test_pdf_that_will_not_download_is_counted_by_cause(self):
        actions, log = run(FakeSession([list_item(24)], {}))
        self.assertEqual(actions[0].date_note, "download")
        self.assertIn("1 PDFs not downloaded (HTTPError 503 x1)", log)


@unittest.skipUnless(ore.TESSERACT, "tesseract is not installed")
class OcrTests(unittest.TestCase):
    def test_signing_date_is_read_from_a_scanned_order(self):
        signed, text, note = ore.ocr_signing_date(scanned_order(SIGNED_ORDER), 2026, TODAY)
        self.assertEqual((signed, note), ("2026-08-07", ""))
        self.assertIn("Salem", text)

    def test_collect_dates_scanned_orders_and_writes_the_source(self):
        pdfs = {url(24): scanned_order(SIGNED_ORDER),
                url(23): scanned_order(["EXECUTIVE ORDER NO. 26-23", "No date on this page."], seed=2)}
        session = FakeSession([list_item(24), list_item(23)], pdfs)
        actions, log = run(session)
        dated = {a.stable_id: (a.signed, a.date_source, a.date_note) for a in actions}
        self.assertEqual(dated["OR-EO-26-24"], ("2026-08-07", ore.DATE_FROM_OCR, ""))
        self.assertEqual(dated["OR-EO-26-23"], ("", "", "not_found"))
        self.assertIn("1 read from the scan by OCR", log)
        self.assertIn("1 not found by OCR", log)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ore.write_outputs(actions, root / "a.csv", root / "r.csv", root / "j.csv", root / "review.csv")
            with (root / "a.csv").open() as handle:
                rows = {row["declaration_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(rows["OR-EO-26-24"]["date_source"], ore.DATE_FROM_OCR)
            self.assertEqual(rows["OR-EO-26-24"]["governor"], "Tina Kotek")
            with (root / "review.csv").open() as handle:
                self.assertEqual([r["declaration_id"] for r in csv.DictReader(handle)], ["OR-EO-26-23"])

    def test_time_limit_leaves_the_rest_for_the_next_run(self):
        session = FakeSession([list_item(24)], {url(24): scanned_order(SIGNED_ORDER)})
        actions, log = run(session, ocr_budget=0)
        self.assertEqual(actions[0].date_note, "budget")
        self.assertIn("1 left for the next run (OCR time limit)", log)


if __name__ == "__main__":
    unittest.main()
