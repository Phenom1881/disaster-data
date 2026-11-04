"""Texas's hand-added declarations (manual_declarations.csv).

The current Governor's proclamation archive starts in January 2015. Weather
disaster proclamations from 2001 to 2014 come from archived copies of the
Governor's proclamation pages (governor.state.tx.us) on the Wayback Machine,
and a few others are dated from news and TDEM coverage. Each row has to reach
the storm join and the page the way a collected declaration does.

Run:  python -m unittest test_tx_manual_declarations
"""
import csv
import importlib.util
import re
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
OVERRIDES = HERE / "hazard_overrides.csv"
JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
HAZARDS = {"fire", "flood", "winter", "severe_storm", "tropical", "storm_general", "wind", "drought", "exclude"}
ARCHIVE = re.compile(r"https://web\.archive\.org/web/(\d{14})/http://governor\.state\.tx\.us/news/proclamation/\d+/")

# Governor (or acting governor) -> (first day in office, first day out).
TERMS = {
    "George W. Bush": (date(1995, 1, 17), date(2000, 12, 21)),
    "Rick Perry": (date(2000, 12, 21), date(2015, 1, 20)),
    "David Dewhurst": (date(2003, 1, 21), date(2015, 1, 20)),
    "Greg Abbott": (date(2015, 1, 20), date(2031, 1, 1)),
}

_SPEC = importlib.util.spec_from_file_location("tx_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def hand_rows():
    return [row for row in read(MANUAL) if not row["declaration_id"].startswith("TX-PROCLAMATION-")]


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_carry_the_signing_date(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        for row in hand_rows():
            self.assertRegex(row["declaration_id"], r"^TX-(PROC|SOE)-\d{4}-\d{2}-\d{2}$")
            self.assertEqual(row["declaration_id"][-10:], row["date_signed"], row["declaration_id"])

    def test_every_row_is_signed_in_its_governors_term(self):
        for row in hand_rows():
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= date.fromisoformat(row["date_signed"]) < end, row["declaration_id"])

    def test_proclamation_rows_link_an_archived_governor_page_saved_after_signing(self):
        for row in hand_rows():
            if not row["declaration_id"].startswith("TX-PROC-"):
                continue
            found = ARCHIVE.fullmatch(row["archive_record_url"])
            self.assertTrue(found, row["declaration_id"])
            self.assertGreaterEqual(found.group(1)[:8], row["date_signed"].replace("-", ""), row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in hand_rows():
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_no_row_is_a_renewal_or_extension(self):
        for row in hand_rows():
            self.assertNotRegex(row["event_description"], r"(?i)\b(?:renew|extend|extension|amend|re-issue|rescind|terminat)")

    def test_every_hand_row_has_a_reviewed_override(self):
        notes = {row["declaration_id"]: row for row in read(OVERRIDES)}
        for row in hand_rows():
            note = notes.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])
            if note["event_date"]:
                self.assertLessEqual(note["event_date"], row["date_signed"], row["declaration_id"])

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
