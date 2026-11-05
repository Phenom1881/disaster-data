"""New York's hand-added declarations (manual_declarations.csv).

The Governor's archive is complete from August 24, 2021, and the Past
Executive Orders page lists only earlier orders still in force, so earlier
weather disaster orders are kept by hand: Governors Pataki, Spitzer and
Paterson's from 9 NYCRR Parts 5, 6 and 7, where their executive orders are
printed with their dates, and Governor Cuomo's from the New York State Register, which prints each order
with its signing line. Each row has to reach the storm join and the page the
way a collected declaration does.

Run:  python -m unittest test_ny_manual_declarations
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
    "George E Pataki": (date(1995, 1, 1), date(2007, 1, 1)),
    "Eliot Spitzer": (date(2007, 1, 1), date(2008, 3, 17)),
    "David A Paterson": (date(2008, 3, 17), date(2011, 1, 1)),
    "Andrew M Cuomo": (date(2011, 1, 1), date(2021, 8, 24)),
}
NYCRR = re.compile(
    r"https://regulations\.justia\.com/states/new-york/title-9/subtitle-a/chapter-i/part-([567])/section-\1-(\d+)/")
# 9 NYCRR part for each governor whose executive orders it prints.
PART = {"George E Pataki": "5", "Eliot Spitzer": "6", "David A Paterson": "7"}
REGISTER = re.compile(r"https://dos\.ny\.gov/([a-z]+)-(\d{1,2})-(\d{4})vol-[xlvi]+-issue-(\d+)")
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
            "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth",
            "seventeenth", "eighteenth", "nineteenth", "twentieth", "twenty-first", "twenty-second",
            "twenty-third", "twenty-fourth", "twenty-fifth", "twenty-sixth", "twenty-seventh",
            "twenty-eighth", "twenty-ninth", "thirtieth", "thirty-first"]
YEARS = {2017: "seventeen", 2018: "eighteen", 2019: "nineteen", 2020: "twenty"}

_SPEC = importlib.util.spec_from_file_location("ny_storm_join", HERE / "eo_storm_join.py")
join = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(join)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def notes():
    return {row["declaration_id"]: row for row in read(OVERRIDES)}


class ManualDeclarationTests(unittest.TestCase):
    def test_columns_match_the_join_file(self):
        with open(MANUAL, newline="", encoding="utf-8") as handle:
            self.assertEqual(next(csv.reader(handle)), JOIN_FIELDS)

    def test_ids_are_unique_and_not_already_collected(self):
        ids = [row["declaration_id"] for row in read(MANUAL)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(ids) & {row["declaration_id"] for row in read(JOIN)})

    def test_ids_follow_the_governor_and_order_number(self):
        for row in read(MANUAL):
            self.assertRegex(row["eo_number"], r"^\d{1,3}$", row["declaration_id"])
            prefix = "NY-" + row["governor"].replace(" ", "").upper() + "-EO-"
            self.assertEqual(row["declaration_id"], prefix + row["eo_number"])

    def test_every_row_is_signed_in_its_governors_term(self):
        for row in read(MANUAL):
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= date.fromisoformat(row["date_signed"]) < end, row["declaration_id"])

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        for row in read(MANUAL):
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_no_row_is_a_renewal_or_extension(self):
        for row in read(MANUAL):
            self.assertNotRegex(row["event_description"], r"(?i)\b(?:renew|extend|extension|continu|amend|rescind|terminat)")

    def test_every_row_has_a_reviewed_override(self):
        reviewed = notes()
        for row in read(MANUAL):
            note = reviewed.get(row["declaration_id"])
            self.assertIsNotNone(note, row["declaration_id"])
            self.assertTrue(set(note["hazard_category_override"].split(",")) <= HAZARDS, row["declaration_id"])
            self.assertEqual(note["source_url"], row["archive_record_url"], row["declaration_id"])

    def test_every_row_links_9_nycrr_or_the_state_register(self):
        for row in read(MANUAL):
            url = row["archive_record_url"]
            self.assertTrue(NYCRR.fullmatch(url) or REGISTER.fullmatch(url), row["declaration_id"])

    def test_nycrr_rows_sit_in_their_governors_part_and_quote_section_and_date(self):
        found_any = False
        for row in read(MANUAL):
            found = NYCRR.fullmatch(row["archive_record_url"])
            if not found:
                continue
            found_any = True
            part, section = found.groups()
            self.assertEqual(PART.get(row["governor"]), part, row["declaration_id"])
            self.assertEqual(section, row["eo_number"], row["declaration_id"])
            signed = date.fromisoformat(row["date_signed"])
            note = notes()[row["declaration_id"]]["review_note"]
            self.assertTrue(note.startswith(f"9 NYCRR {part}.{row['eo_number']}, Executive Order No. {row['eo_number']}: '"), note)
            self.assertIn(f"'Dated: {MONTHS[signed.month - 1]} {signed.day}, {signed.year}'", note)
        self.assertTrue(found_any)

    def test_register_rows_are_cuomos_and_quote_the_signing_line(self):
        found_any = False
        for row in read(MANUAL):
            found = REGISTER.fullmatch(row["archive_record_url"])
            if not found:
                continue
            found_any = True
            self.assertEqual(row["governor"], "Andrew M Cuomo", row["declaration_id"])
            month, day, year, _ = found.groups()
            issue = date(int(year), MONTHS.index(month.capitalize()) + 1, int(day))
            signed = date.fromisoformat(row["date_signed"])
            self.assertLess(signed, issue, row["declaration_id"])
            note = notes()[row["declaration_id"]]["review_note"]
            self.assertTrue(note.startswith(
                f"New York State Register, {MONTHS[issue.month - 1]} {issue.day}, {issue.year}, "
                f"Executive Order No. {row['eo_number']}: '"), note)
            self.assertIn(f"'this {ORDINALS[signed.day - 1]} day of {MONTHS[signed.month - 1]} "
                          f"in the year two thousand {YEARS[signed.year]}'", note)
        self.assertTrue(found_any)

    def test_the_coverage_note_starts_in_2000_and_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("ny_adapter", HERE / "new_york.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "NY")
        self.assertEqual(adapter.COVERAGE_NOTE, note)
        self.assertTrue(note.startswith("2000-present: "), note)
        rows = read(MANUAL)
        self.assertIn(f"plus {len(rows)} weather disaster orders added by hand", note)
        pataki = sum(1 for row in rows if row["governor"] == "George E Pataki")
        cuomo = sum(1 for row in rows if row["governor"] == "Andrew M Cuomo")
        spitzer = sum(1 for row in rows if row["governor"] == "Eliot Spitzer")
        paterson = sum(1 for row in rows if row["governor"] == "David A Paterson")
        self.assertIn(f"{pataki} Pataki orders", note)
        self.assertIn(f"{spitzer} Spitzer order", note)
        self.assertIn(f"{paterson} Paterson orders", note)
        self.assertIn(f"{cuomo} Cuomo orders", note)

    def test_the_named_gaps_are_counted_and_named_once(self):
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s["coverage_note"] for s in manifest["states"] if s["abbreviation"] == "NY")
        self.assertEqual(len(re.findall(r"\b(?:DR|EM)-\d{4}\b", note)),
                         len(set(re.findall(r"\b(?:DR|EM)-\d{4}\b", note))))
        gaps = re.search(r"No state order is kept yet for (\d+) federal declarations from [^:]*: (.*?\))\. ", note)
        self.assertIsNotNone(gaps, note)
        named = re.findall(r"\b(?:DR|EM)-\d{4}\b", gaps.group(2))
        self.assertEqual(int(gaps.group(1)), len(named))

    def test_no_long_dashes(self):
        for path in (MANUAL, OVERRIDES, HERE / "new_york.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text)
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
