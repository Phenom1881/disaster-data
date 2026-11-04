"""2000-2008 disaster emergency orders added by hand from Oklahoma
Administrative Code Title 1 (Executive Orders).

Each row's date is the signing date Title 1 gives for the order, and its
record URL is that order's section of Title 1.
"""
import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TITLE1 = "https://www.law.cornell.edu/regulations/oklahoma/OAC-1-"
EXPECTED = {
    "2000-33": "2000-10-30", "2000-37": "2000-12-27", "2001-20": "2001-05-30",
    "2001-34": "2001-10-10", "2002-2": "2002-01-30", "2002-14": "2002-12-04",
    "2003-10": "2003-05-09", "2005-31": "2005-11-28", "2006-7": "2006-03-14",
    "2007-26": "2007-06-12", "2007-36": "2007-08-20", "2007-49": "2007-12-10",
    "2008-19": "2008-05-11", "2008-24": "2008-06-11", "2008-38": "2008-09-15",
}
# Lieutenant Governors signed some orders as acting Governor.
SIGNERS = {"Frank Keating", "Brad Henry", "Mary Fallin", "Jari Askins"}


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def title1_rows():
    return [r for r in csv_rows("manual_declarations.csv") if r["archive_record_url"].startswith(TITLE1)]


class Title1OrderTests(unittest.TestCase):
    def test_signing_dates(self):
        self.assertEqual({r["eo_number"]: r["date_signed"] for r in title1_rows()}, EXPECTED)

    def test_ids_urls_and_signers(self):
        ids = [r["declaration_id"] for r in csv_rows("manual_declarations.csv")]
        self.assertEqual(len(ids), len(set(ids)))
        for row in title1_rows():
            self.assertEqual(row["declaration_id"], "OK-SOE-" + row["date_signed"])
            self.assertEqual(row["archive_record_url"], TITLE1 + row["eo_number"])
            self.assertEqual(row["eo_number"][:4], row["date_signed"][:4])
            self.assertIn(row["governor"], SIGNERS)

    def test_each_has_a_reviewed_hazard(self):
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        for row in title1_rows():
            override = overrides[row["declaration_id"]]
            self.assertEqual(override["source_url"], row["archive_record_url"])
            self.assertEqual(override["review_note"], "Executive Order %s, signed %s; Oklahoma Administrative "
                             "Code Title 1, section 1:%s." % (row["eo_number"], row["date_signed"], row["eo_number"]))
            self.assertLessEqual(set(override["hazard_category_override"].split(",")),
                                 {"severe_storm", "flood", "winter", "fire"})


class CoverageStartTests(unittest.TestCase):
    def test_note_matches_and_starts_in_2000(self):
        manifest = json.loads((ROOT / "scripts" / "plus" / "state-manifest.json").read_text(encoding="utf-8"))
        note = next(s for s in manifest["states"] if s["abbreviation"] == "OK")["coverage_note"]
        adapter_text = (HERE / "oklahoma.py").read_text(encoding="utf-8")
        self.assertIn('"2000-present: Oklahoma Emergency', adapter_text)
        spec = importlib.util.spec_from_file_location("build_plus_ok", ROOT / "scripts" / "build-plus.py")
        build = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = build
        spec.loader.exec_module(build)
        self.assertEqual(build.coverage_start_year("OK", note), 2000)


if __name__ == "__main__":
    unittest.main()
