"""Oregon declarations added by hand that the Governor's online archive lacks."""
import csv
import importlib.util
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_eo_06_01_dated_from_the_oregon_bulletin(self):
        rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        row = rows["OR-SOE-2006-01-13"]
        self.assertEqual(row["date_signed"], "2006-01-13")
        self.assertEqual(row["eo_number"], "06-01")
        self.assertEqual(row["governor"], "Theodore R. Kulongoski")
        self.assertEqual(row["archive_record_url"], "https://www.oregon.gov/gov/eo/eo0601.pdf")

    def test_each_manual_row_has_a_reviewed_override(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in csv_rows("manual_declarations.csv"):
            if row["declaration_id"] != "OR-SOE-2006-01-13":
                continue
            override = overrides[row["declaration_id"]]
            self.assertEqual(override["source_url"], row["archive_record_url"])
            self.assertEqual(set(override["hazard_category_override"].split(",")), {"flood", "severe_storm"})
            self.assertEqual(override["event_date"], "2005-12-22")

    def test_eo_06_01_is_not_already_a_joined_declaration(self):
        joined = {r["eo_number"] for r in csv_rows("declarations_for_join.csv")}
        self.assertNotIn("06-01", joined)
        self.assertIn("Record/4539413", {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}["OR-SOE-2006-01-13"]["review_note"])


KITZHABER_SITE = "https://records.sos.state.or.us/ORSOSWebDrawer/Record/5969211/File/document"
KITZHABER_SOURCE = "Oregon State Archives copy of Governor Kitzhaber's website, January 13, 2003 (Record APD/18/19)"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
# Orders in Kitzhaber's 2000-2002 index left out on purpose: fires proclaimed
# before 2000 (00-10 to 00-15), a Washington fire (00-16), a bridge failure
# (00-29), drought orders with a blank signing day (01-03, 01-04, 01-05) and an
# index entry with no text (02-06).
LEFT_OUT = {"00-10", "00-11", "00-12", "00-13", "00-14", "00-15", "00-16", "00-29",
            "01-03", "01-04", "01-05", "02-06"}


def kitzhaber_rows():
    return [r for r in csv_rows("manual_declarations.csv") if r["governor"] == "John A. Kitzhaber"]


class KitzhaberOrderTests(unittest.TestCase):
    def test_ids_numbers_and_dates_agree(self):
        rows = kitzhaber_rows()
        self.assertTrue(rows)
        for row in rows:
            number = row["eo_number"]
            self.assertRegex(number, r"^0[0-2]-\d{2}$", row["declaration_id"])
            self.assertEqual(row["declaration_id"], "OR-EO-" + number)
            self.assertEqual(row["date_signed"][:4], "20" + number[:2], row["declaration_id"])
            self.assertTrue("2000-01-01" <= row["date_signed"] < "2003-01-13", row["declaration_id"])
            self.assertEqual(row["archive_record_url"], KITZHABER_SITE, row["declaration_id"])

    def test_each_order_has_a_cited_override_quoting_its_date(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in kitzhaber_rows():
            note = overrides[row["declaration_id"]]
            self.assertEqual(note["source_url"], KITZHABER_SITE, row["declaration_id"])
            self.assertTrue(note["review_note"].startswith(KITZHABER_SOURCE + ", PDF page "), row["declaration_id"])
            year, month, day = row["date_signed"].split("-")
            name = MONTHS[int(month) - 1]
            spoken = f"{name} {int(day)}, {year}"
            written = re.compile(rf"\b_*{int(day)}\s*(?:st|nd|rd|th)?_* ?_*day of {name}, {year}")
            self.assertTrue(spoken in note["review_note"] or written.search(note["review_note"]), row["declaration_id"])
            hazard = note["hazard_category_override"]
            if "drought" in row["event_description"]:
                self.assertEqual(hazard, "drought", row["declaration_id"])
            elif "wildfire" in row["event_description"]:
                self.assertEqual(hazard, "fire", row["declaration_id"])
            else:
                self.assertEqual(hazard, "flood", row["declaration_id"])

    def test_orders_left_out_on_purpose_stay_out(self):
        numbers = {r["eo_number"] for r in kitzhaber_rows()}
        self.assertFalse(numbers & LEFT_OUT)

    def test_the_coverage_note_starts_in_2000_and_counts_the_orders(self):
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "OR")
        self.assertTrue(note.startswith("2000-present: "), note)
        spec = importlib.util.spec_from_file_location("or_adapter", HERE / "oregon.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        self.assertEqual(adapter.COVERAGE_NOTE, note)
        self.assertIn(f"plus {len(kitzhaber_rows())} weather emergency orders from 2000-2002", note)
        for gap in ("DR-1405", "DR-1510", "DR-1683", "DR-4296"):
            self.assertIn(gap, note)

    def test_no_long_dashes(self):
        for name in ("manual_declarations.csv", "hazard_overrides.csv"):
            text = (HERE / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
