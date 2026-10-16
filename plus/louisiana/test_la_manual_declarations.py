"""Louisiana's hand-added declarations (manual_declarations.csv).

Governor Edwards (January 2016 to January 2024) declared weather emergencies
by proclamation, and no index of his proclamations is published, so the ones
FMCSA's archive does not carry are kept by hand. Each row has to reach the
storm join and the page the way a collected declaration does.

Run:  python -m unittest test_la_manual_declarations
"""
import csv
import importlib.util
import re
import unittest
from datetime import date
from pathlib import Path

import la_eo_scraper as la

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "manual_declarations.csv"
EDWARDS_TERM = (date(2016, 1, 11), date(2024, 1, 8))
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

    def test_every_row_is_an_edwards_declaration_signed_in_his_term(self):
        for row in rows():
            signed = date.fromisoformat(row["date_signed"])
            self.assertEqual(row["governor"], "John Bel Edwards", row["declaration_id"])
            self.assertTrue(EDWARDS_TERM[0] <= signed < EDWARDS_TERM[1], row["declaration_id"])

    def test_the_id_says_whether_the_proclamation_number_is_known(self):
        ids = [row["declaration_id"] for row in rows()]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows():
            number = row["eo_number"]
            if number:
                found = re.fullmatch(r"(\d{1,3}) JBE (\d{4})", number)
                self.assertTrue(found, number)
                self.assertEqual(found.group(2), row["date_signed"][:4], number)
                self.assertEqual(row["declaration_id"], f"LA-PROC-{found.group(1)}-JBE-{found.group(2)}")
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

    def test_no_long_dashes(self):
        text = MANUAL.read_text(encoding="utf-8")
        self.assertNotIn("\u2013", text)
        self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
