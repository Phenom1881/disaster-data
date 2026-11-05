"""Michigan's hand-added declarations (manual_declarations.csv).

The current Governor's archive starts with Governor Whitmer in 2019. Earlier
weather declarations behind federal declarations are kept by hand from the
former Governors' archive on michigan.gov and dated news coverage. Each row
has to reach the storm join and the page the way a collected declaration
does.

Run:  python -m unittest test_mi_manual_declarations
"""
import csv
import importlib.util
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN = HERE / "declarations_for_join.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought"}
TERMS = {
    "Jennifer Granholm": ("2003-01-01", "2011-01-01"),
    "Rick Snyder": ("2011-01-01", "2019-01-01"),
}
# A Lieutenant Governor acting for the Governor, by signing date.
ACTING = {"2017-06-23": "Brian Calley"}
FORMER = "https://www.michigan.gov/formergovernors/recent/"


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_follow_the_order_number_or_the_signing_date_and_are_new(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(ids) & {row["declaration_id"] for row in read(JOIN)})
        for row in read(MANUAL):
            if row["eo_number"]:
                self.assertRegex(row["eo_number"], r"^\d{4}-\d{1,3}$")
                self.assertEqual(row["eo_number"][:4], row["date_signed"][:4], row["declaration_id"])
                self.assertEqual(row["declaration_id"], "MI-EO-" + row["eo_number"])
            else:
                self.assertEqual(row["declaration_id"], "MI-SOE-" + row["date_signed"])

    def test_every_row_is_signed_before_2019_by_the_governor_or_the_known_acting_one(self):
        for row in read(MANUAL):
            day = row["date_signed"]
            self.assertLess(day, "2019-01-01", row["declaration_id"])
            if day in ACTING:
                self.assertEqual(row["governor"], ACTING[day], row["declaration_id"])
                continue
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= day < end, row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        spec = importlib.util.spec_from_file_location("mi_storm_join", HERE / "eo_storm_join.py")
        join = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(join)
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_every_row_has_a_reviewed_note_quoting_its_source(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in read(MANUAL):
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            self.assertIn("'", note["review_note"], row["declaration_id"])
            self.assertTrue(note["event_date"], row["declaration_id"])
            self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])
            if row["archive_record_url"].startswith(FORMER) and "/press-releases/" in row["archive_record_url"]:
                found = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", row["archive_record_url"])
                self.assertEqual("-".join(found.groups()), row["date_signed"], row["declaration_id"])

    def test_the_coverage_note_starts_in_2000_and_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("mi_adapter", HERE / "michigan.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "MI")
        self.assertEqual(adapter.COVERAGE_NOTE, note)
        self.assertTrue(note.startswith("2000-present: "), note)
        self.assertIn(f"plus {len(read(MANUAL))} weather declarations added by hand", note)

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES, Path(__file__), HERE / "michigan.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
