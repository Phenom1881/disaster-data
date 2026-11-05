"""Florida's hand-added declarations (manual_declarations.csv).

The Governor's current archive starts in 2020 and the State Library's order
archive disallows crawlers, so 2000-2019 weather emergency orders are kept by
hand: Bush orders from 2000-2003 read one at a time from the State Library
archive (not crawled), Bush and Crist orders catalogued with their dates by
the FSU College of Law collection on Florida Government Documents, and later
orders dated from order copies, archived Governor pages and news coverage. Each row has to reach
the storm join and the page the way a collected declaration does.

Run:  python -m unittest test_fl_manual_declarations
"""
import csv
import importlib.util
import json
import re
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN = HERE / "declarations_for_join.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought", "exclude"}
TERMS = {
    "Jeb Bush": (date(1999, 1, 5), date(2007, 1, 2)),
    "Charlie Crist": (date(2007, 1, 2), date(2011, 1, 4)),
    "Rick Scott": (date(2011, 1, 4), date(2019, 1, 8)),
    "Ron DeSantis": (date(2019, 1, 8), date(2027, 1, 5)),
}
OMEKA = "https://flgovdocs.omeka.net/items/show/"
STATE_LIBRARY = re.compile(r"https://edocs\.dos\.fl\.gov/fldocs/governor/orders/(\d{4})/(\d{2})-(\d{2,3})\.pdf")

_SPEC = importlib.util.spec_from_file_location("fl_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_not_already_collected(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(ids) & {row["declaration_id"] for row in read(JOIN)})

    def test_ids_follow_the_order_number_or_the_signing_date(self):
        for row in read(MANUAL):
            number = row["eo_number"]
            if number:
                found = re.fullmatch(r"(\d{4})-(\d{1,3})", number)
                self.assertTrue(found, row["declaration_id"])
                self.assertEqual(found.group(1), row["date_signed"][:4], row["declaration_id"])
                self.assertEqual(row["declaration_id"], "FL-EO-" + number)
            else:
                self.assertEqual(row["declaration_id"], "FL-SOE-" + row["date_signed"])

    def test_every_row_is_signed_in_its_governors_term(self):
        for row in read(MANUAL):
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= date.fromisoformat(row["date_signed"]) < end, row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_every_row_has_a_reviewed_override(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])

    def test_catalogued_orders_quote_their_number_and_date(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            if not row["archive_record_url"].startswith(OMEKA):
                continue
            number = row["eo_number"][2:]  # "2004-182" -> "04-182"
            self.assertIn("Fla. Exec. Order No. " + number, notes[row["declaration_id"]]["review_note"])
            self.assertIn(row["date_signed"], notes[row["declaration_id"]]["review_note"])

    def test_state_library_orders_link_their_own_pdf_and_quote_it(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        found_any = False
        for row in read(MANUAL):
            found = STATE_LIBRARY.fullmatch(row["archive_record_url"])
            if not found:
                self.assertNotIn("edocs.dos.fl.gov", row["archive_record_url"], row["declaration_id"])
                continue
            found_any = True
            year, short, number = found.groups()
            self.assertEqual(short, year[2:], row["declaration_id"])
            self.assertEqual(row["eo_number"], f"{year}-{int(number)}", row["declaration_id"])
            note = notes[row["declaration_id"]]["review_note"]
            self.assertIn(f"Executive Order Number {short}-{number}, signed {row['date_signed']}:", note)
            self.assertIn("state of emergency exists", note, row["declaration_id"])
            self.assertIn("not crawled", note, row["declaration_id"])
        self.assertTrue(found_any)

    def test_no_row_is_a_renewal_or_extension(self):
        for row in read(MANUAL):
            self.assertNotRegex(row["event_description"], r"(?i)\b(?:renew|extend|extension|amend|rescind|terminat)")

    def test_the_coverage_note_starts_in_2000_and_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("fl_adapter", HERE / "florida.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "FL")
        self.assertEqual(adapter.COVERAGE_NOTE, note)
        self.assertTrue(note.startswith("2000-present: "), note)
        self.assertIn(f"plus {len(read(MANUAL))} weather emergency orders added by hand", note)
        library = sum(1 for row in read(MANUAL) if STATE_LIBRARY.fullmatch(row["archive_record_url"]))
        self.assertIn(f"{library} Bush orders from 2000-2003", note)

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
