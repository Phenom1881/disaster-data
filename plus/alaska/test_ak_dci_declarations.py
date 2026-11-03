"""Alaska state disaster declarations added by hand from DHS&EM's Disaster
Cost Index (as printed in the 2013, 2018 and 2023 State Hazard Mitigation
Plans) and from DHS&EM releases.

Each row's date is the declaration date the source gives. Where the state
declared weeks after the event, the override carries the event's start date
so the declaration is compared against the right federal incident.
"""
import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DCI13 = "https://web.archive.org/web/2014/http://ready.alaska.gov/plans/documents/Alaska%20HMP%202013%20sm.pdf"
DCI18 = "https://web.archive.org/web/2022/https://ready.alaska.gov/Documents/Mitigation/StatePlan/Ch13-Appendices.pdf"
GOVERNORS = [("1994-12-05", "Tony Knowles"), ("2002-12-02", "Frank Murkowski"), ("2006-12-04", "Sarah Palin"),
             ("2009-07-26", "Sean Parnell"), ("2014-12-01", "Bill Walker"), ("2018-12-03", "Mike Dunleavy")]
DCI_DATES = {
    "AK-PROC-2002-05-29": "DR-1423", "AK-PROC-2002-11-06": "DR-1445", "AK-PROC-2003-03-28": "DR-1461",
    "AK-PROC-2005-01-15": "DR-1584", "AK-PROC-2005-10-24": "DR-1618", "AK-PROC-2006-06-27": "DR-1657",
    "AK-PROC-2006-08-06": "DR-1666", "AK-PROC-2006-08-29": "DR-1663", "AK-PROC-2006-10-14": "DR-1669",
    "AK-PROC-2011-05-17": "DR-1992", "AK-PROC-2013-11-18": "DR-4161", "AK-PROC-2015-10-14": "DR-4244",
    "AK-PROC-2016-01-29": "DR-4257", "AK-PROC-2017-11-14": "DR-4351", "AK-PROC-2018-01-19": "DR-4369",
}
RELEASE_DATES = ["2022-05-07", "2022-05-13", "2023-05-15", "2023-11-21", "2024-08-06", "2024-08-25",
                 "2025-10-09", "2025-12-10"]
LATE_DECLARATION_EVENTS = {"AK-PROC-2009-11-06": "2009-10-09", "AK-PROC-2011-12-06": "2011-11-08"}


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def governor_on(day):
    current = None
    for start, name in GOVERNORS:
        if day >= start:
            current = name
    return current


class DisasterCostIndexTests(unittest.TestCase):
    def setUp(self):
        self.rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        self.overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}

    def test_dci_rows_name_their_entry_and_federal_number(self):
        for declaration_id, federal in DCI_DATES.items():
            row = self.rows[declaration_id]
            self.assertEqual(row["date_signed"], declaration_id[len("AK-PROC-"):])
            self.assertIn(row["archive_record_url"], {DCI13, DCI18} | {self.overrides[declaration_id]["source_url"]})
            note = self.overrides[declaration_id]["review_note"]
            self.assertIn(federal + ".", note)
            self.assertTrue("DCI" in note or "Disaster Cost Index" in note, declaration_id)

    def test_release_rows_cite_dhsem_or_news(self):
        for day in RELEASE_DATES:
            row = self.rows["AK-PROC-" + day]
            self.assertEqual(row["date_signed"], day)
            self.assertEqual(row["governor"], "Mike Dunleavy")
            self.assertEqual(self.overrides[row["declaration_id"]]["source_url"], row["archive_record_url"])

    def test_governor_in_office_and_event_not_after_declaration(self):
        for declaration_id in list(DCI_DATES) + ["AK-PROC-" + d for d in RELEASE_DATES]:
            row = self.rows[declaration_id]
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), declaration_id)
            event = self.overrides[declaration_id]["event_date"]
            if event:
                self.assertLessEqual(event, row["date_signed"], declaration_id)

    def test_late_declarations_carry_the_event_start(self):
        for declaration_id, event in LATE_DECLARATION_EVENTS.items():
            self.assertIn(declaration_id, self.rows)
            self.assertEqual(self.overrides[declaration_id]["event_date"], event)

    def test_hazards_are_known_categories(self):
        allowed = {"flood", "severe_storm", "winter", "wind", "fire", "storm_general"}
        for declaration_id in list(DCI_DATES) + ["AK-PROC-" + d for d in RELEASE_DATES]:
            self.assertLessEqual(set(self.overrides[declaration_id]["hazard_category_override"].split(",")), allowed)


class CoverageStartTests(unittest.TestCase):
    def test_alaska_compares_from_2000_and_names_its_gaps(self):
        spec = importlib.util.spec_from_file_location("build_plus_ak", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = build
        spec.loader.exec_module(build)
        manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s for s in manifest["states"] if s["abbreviation"] == "AK")["coverage_note"]
        self.assertEqual(build.coverage_start_year("AK", note), 2000)
        for federal in ("DR-4391", "DR-4638"):
            self.assertIn(federal, note)


if __name__ == "__main__":
    unittest.main()
