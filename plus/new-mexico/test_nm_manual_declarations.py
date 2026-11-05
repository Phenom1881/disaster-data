"""New Mexico's hand-added declarations (manual_declarations.csv).

The current Governor's archive starts in 2019 and no public index of earlier
executive orders was found, so 2006-2013 weather declarations by Governors
Richardson and Martinez are kept by hand from executive orders reprinted in
the press and dated news coverage. Each row has to reach the storm join and
the page the way a collected declaration does.

Run:  python -m unittest test_nm_manual_declarations
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
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought"}
TERMS = {
    "Gary Johnson": (date(1995, 1, 1), date(2003, 1, 1)),
    "Bill Richardson": (date(2003, 1, 1), date(2011, 1, 1)),
    "Susana Martinez": (date(2011, 1, 1), date(2019, 1, 1)),
}
# The scraped current-Governor archive starts here.
SCRAPED_FROM = date(2019, 1, 1)

_SPEC = importlib.util.spec_from_file_location("nm_storm_join", HERE / "eo_storm_join.py")
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
                found = re.fullmatch(r"(\d{4})-(\d{3})", number)
                self.assertTrue(found, row["declaration_id"])
                self.assertEqual(found.group(1), row["date_signed"][:4], row["declaration_id"])
                self.assertEqual(row["declaration_id"], "NM-EO-" + number)
            else:
                self.assertEqual(row["declaration_id"], "NM-SOE-" + row["date_signed"])

    def test_every_row_is_signed_in_its_governors_term_before_the_scraped_archive(self):
        for row in read(MANUAL):
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            signed = date.fromisoformat(row["date_signed"])
            self.assertTrue(start <= signed < end, row["declaration_id"])
            self.assertLess(signed, SCRAPED_FROM, row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_every_row_has_a_reviewed_override_citing_its_source(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertIn(note["hazard_category_override"], HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            self.assertTrue(row["archive_record_url"].startswith("https://"), row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])
            if row["eo_number"]:
                self.assertIn("Executive Order " + row["eo_number"], note["review_note"], row["declaration_id"])

    def test_report_dated_rows_say_so(self):
        notes = {row["declaration_id"]: row["review_note"] for row in read(OVERRIDES)}
        for row in read(MANUAL):
            note = notes[row["declaration_id"]]
            if "does not give the day" in note:
                self.assertIn("carries the date of the report", note, row["declaration_id"])

    def test_no_row_is_a_renewal_or_funding_only_order(self):
        for row in read(MANUAL):
            self.assertNotRegex(row["event_description"],
                                r"(?i)\b(?:renew|extend|extension|amend|rescind|terminat|additional funding|emac)")

    def test_the_coverage_note_starts_in_2000_and_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("nm_adapter", HERE / "new_mexico.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "NM")
        self.assertEqual(adapter.COVERAGE_NOTE, note)
        self.assertTrue(note.startswith("2000-present: "), note)
        self.assertIn(f"plus {len(read(MANUAL))} weather declarations added by hand", note)

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES, Path(__file__), HERE / "new_mexico.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
