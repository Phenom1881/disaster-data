"""Mississippi's hand-added declarations (manual_declarations.csv).

Two kinds of row are kept by hand. MS-EO- rows are 2000-2010 executive
orders from the Secretary of State's compilations. MS-SOE- rows are state of
emergency proclamations, which Mississippi does not number or index, taken
from MEMA's newsroom and dated news coverage. Each row has to reach the storm
join and the page the way a collected declaration does.

Run:  python -m unittest test_ms_manual_declarations
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
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought"}
# Who signed: governors by term, and the Lieutenant Governor acting for one.
TERMS = {
    "Ronnie Musgrove": ("2000-01-11", "2004-01-13"),
    "Haley Barbour": ("2004-01-13", "2012-01-10"),
    "Phil Bryant": ("2012-01-10", "2020-01-14"),
    "Tate Reeves": ("2020-01-14", "2028-01-11"),
}
ACTING = {"2021-02-14": "Delbert Hosemann"}
REPORT_DATED = "so the row carries the date of the report"
# A story URL that carries its date: /2020/04/12/ or /2014/1224/.
URL_DATE = re.compile(r"/(20\d\d)/(\d\d)/?(\d\d)/")


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def proclamations():
    return [row for row in read(MANUAL) if row["declaration_id"].startswith("MS-SOE-")]


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_follow_the_order_number_or_the_signing_date(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        for row in read(MANUAL):
            if row["eo_number"]:
                self.assertEqual(row["declaration_id"], "MS-EO-" + row["eo_number"])
            else:
                self.assertEqual(row["declaration_id"], "MS-SOE-" + row["date_signed"])

    def test_every_row_is_signed_by_the_governor_in_office_or_the_known_acting_one(self):
        for row in read(MANUAL):
            day = row["date_signed"]
            if day in ACTING:
                self.assertEqual(row["governor"], ACTING[day], row["declaration_id"])
                continue
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= day < end, row["declaration_id"])

    def test_proclamation_rows_name_a_hazard_the_storm_join_reads(self):
        spec = importlib.util.spec_from_file_location("ms_storm_join", HERE / "eo_storm_join.py")
        join = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(join)
        for row in proclamations():
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])
            self.assertRegex(row["event_description"], r"^State of emergency|^Emergency declared")

    def test_every_proclamation_has_a_reviewed_note_quoting_its_source(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in proclamations():
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            self.assertTrue(row["archive_record_url"].startswith("https://"), row["declaration_id"])
            self.assertIn("'", note["review_note"], row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])
            if "does not give the day" in note["review_note"]:
                self.assertIn(REPORT_DATED, note["review_note"], row["declaration_id"])

    def test_a_dated_story_url_is_from_the_signing_day_or_the_day_after(self):
        for row in proclamations():
            found = URL_DATE.search(row["archive_record_url"])
            if not found:
                continue
            story = date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
            gap = (story - date.fromisoformat(row["date_signed"])).days
            self.assertIn(gap, (0, 1), row["declaration_id"])

    def test_no_proclamation_is_a_renewal_or_extension(self):
        for row in proclamations():
            self.assertNotRegex(row["event_description"], r"(?i)\b(?:renew|extend|extension|amend|rescind|terminat)")

    def test_overrides_keep_one_row_per_id(self):
        with open(OVERRIDES, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames,
                             ["declaration_id", "hazard_category_override", "review_note", "source_url", "event_date"])
            ids = [row["declaration_id"] for row in reader]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_coverage_note_starts_in_2000_and_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("ms_adapter", HERE / "mississippi.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "MS")
        self.assertEqual(adapter.NOTE, note)
        self.assertTrue(note.startswith("2000-present: "), note)
        self.assertIn(f"plus {len(proclamations())} state of emergency proclamations", note)

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES, Path(__file__), HERE / "mississippi.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
