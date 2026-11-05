"""Louisiana's hand-added declarations (manual_declarations.csv).

Louisiana governors declare weather emergencies by proclamation, and no index
of proclamations is published, so the ones FMCSA's archive does not carry are
kept by hand: Governor Edwards (2016-2024) from his proclamations and news
coverage, Governors Blanco and Jindal (2004-2015) from proclamations
cited in the monthly Louisiana Register and news coverage, and Governor
Foster (2000-2003) from his executive orders printed in the Louisiana
Register and news coverage. Each row has to
reach the storm join and the page the way a collected declaration does.

Run:  python -m unittest test_la_manual_declarations
"""
import csv
import importlib.util
import json
import re
import unittest
from datetime import date
from pathlib import Path

import la_eo_scraper as la

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
# Governor -> (proclamation initials, first day in office, first day out).
TERMS = {
    "Mike Foster": ("MJF", date(1996, 1, 8), date(2004, 1, 12)),
    "Kathleen Babineaux Blanco": ("KBB", date(2004, 1, 12), date(2008, 1, 14)),
    "Bobby Jindal": ("BJ", date(2008, 1, 14), date(2016, 1, 11)),
    "John Bel Edwards": ("JBE", date(2016, 1, 11), date(2024, 1, 8)),
}
SAME_EVENT_DAYS = 5   # plus_fmcsa.DUPLICATE_DAYS: rows this close are one event

_SPEC = importlib.util.spec_from_file_location("la_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def rows():
    with open(MANUAL, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), list(la.JOIN_FIELDS))

    def test_every_row_is_signed_in_its_governors_term(self):
        for row in rows():
            signed = date.fromisoformat(row["date_signed"])
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            _, start, end = TERMS[row["governor"]]
            self.assertTrue(start <= signed < end, row["declaration_id"])

    def test_the_id_says_whether_the_proclamation_number_is_known(self):
        ids = [row["declaration_id"] for row in rows()]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows():
            number = row["eo_number"]
            if number and row["declaration_id"].startswith("LA-EO-"):
                # An executive order, numbered by initials and two-digit year.
                found = re.fullmatch(r"(%s) (\d{2})-(\d{1,3})" % TERMS[row["governor"]][0], number)
                self.assertTrue(found, number)
                self.assertEqual(found.group(2), row["date_signed"][2:4], number)
                self.assertEqual(row["declaration_id"], "LA-EO-" + number.replace(" ", "-"))
            elif number:
                initials = TERMS[row["governor"]][0]
                found = re.fullmatch(r"(\d{1,3}) %s (\d{4})" % initials, number)
                self.assertTrue(found, number)
                self.assertEqual(found.group(2), row["date_signed"][:4], number)
                self.assertEqual(row["declaration_id"], f"LA-PROC-{found.group(1)}-{initials}-{found.group(2)}")
            else:
                self.assertEqual(row["declaration_id"], "LA-SOE-" + row["date_signed"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in rows():
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_no_row_is_a_renewal_or_amendment(self):
        for row in rows():
            self.assertNotRegex(row["event_description"], r"(?i)\b(?:renew|extend|extension|amend|rescind|terminat)")

    def test_no_two_rows_are_the_same_event(self):
        signed = sorted(date.fromisoformat(row["date_signed"]) for row in rows())
        for earlier, later in zip(signed, signed[1:]):
            self.assertGreater((later - earlier).days, SAME_EVENT_DAYS, (earlier, later))

    def test_every_row_links_its_source(self):
        for row in rows():
            self.assertTrue(row["archive_record_url"].startswith("https://"), row["declaration_id"])

    def test_register_rows_cite_the_louisiana_register(self):
        with open(HERE / "hazard_overrides.csv", newline="", encoding="utf-8") as handle:
            notes = {row["declaration_id"]: row for row in csv.DictReader(handle)}
        for row in rows():
            if row["governor"] == "John Bel Edwards":
                continue
            self.assertIn(row["declaration_id"], notes, row["declaration_id"])
            note = notes[row["declaration_id"]]
            if re.match(r"https://doa\.(?:louisiana|la)\.gov/media/", row["archive_record_url"]):
                self.assertIn("Louisiana Register", note["review_note"], row["declaration_id"])
                self.assertIn(row["eo_number"], note["review_note"], row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])

    def test_the_coverage_note_starts_in_2000_and_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("la_adapter", HERE / "louisiana.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "LA")
        self.assertEqual(adapter.COVERAGE_NOTE, note)
        self.assertTrue(note.startswith("2000-present: "), note)
        self.assertIn(f"plus {len(rows())} weather declarations added by hand", note)

    def test_no_long_dashes(self):
        text = MANUAL.read_text(encoding="utf-8")
        self.assertNotIn("\u2013", text)
        self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
