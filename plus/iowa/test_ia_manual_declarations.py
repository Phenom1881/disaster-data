"""Iowa's 2000-2023 weather disaster proclamations, added by hand.

HSEMD's tables start in 2024. Each 2020-2023 row is one proclamation announced
in the Governor's newsroom, which begins in March 2020. Extensions, COVID-19,
avian influenza, harvest and fuel proclamations, and the 2023 building
collapse are left out. No list of the 2000-2019 proclamations has been found,
so those rows come from dated news coverage, mostly Radio Iowa, one for each
federal weather declaration a proclamation could be found for.
"""
import csv
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
NEWSROOM = "https://governor.iowa.gov/press-release/"
RADIO_IOWA = re.compile(r"https://www\.radioiowa\.com/(\d{4})/(\d{2})/(\d{2})/[a-z0-9-]+/")
# Governor -> (first day in office, first day out).
TERMS = {
    "Tom Vilsack": ("1999-01-15", "2007-01-12"),
    "Chet Culver": ("2007-01-12", "2011-01-14"),
    "Terry Branstad": ("2011-01-14", "2017-05-24"),
    "Kim Reynolds": ("2017-05-24", "2031-01-01"),
}
REPORT_DATED = "so the row carries the date of the report"


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def newsroom_rows():
    return [r for r in csv_rows("manual_declarations.csv") if r["date_signed"] >= "2020-03-01"]


def news_rows():
    return [r for r in csv_rows("manual_declarations.csv") if r["date_signed"] < "2020-03-01"]


class HandAddedProclamationTests(unittest.TestCase):
    def test_rows_span_2020_to_2023_and_link_the_release_of_their_date(self):
        rows = newsroom_rows()
        self.assertEqual(len(rows), 39)
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            day = row["date_signed"]
            self.assertTrue("2020-03-01" <= day < "2024-01-01", row["declaration_id"])
            self.assertTrue(row["declaration_id"].startswith("IA-GOV-" + day + "-"), row["declaration_id"])
            self.assertTrue(row["archive_record_url"].startswith(NEWSROOM + day + "/"), row["declaration_id"])
            self.assertEqual(row["governor"], "Kim Reynolds")

    def test_derecho_and_december_2021_proclamations(self):
        rows = {r["declaration_id"]: r for r in csv_rows("manual_declarations.csv")}
        self.assertIn("Boone", rows["IA-GOV-2020-08-11-six-counties"]["event_description"])
        self.assertIn("43 counties", rows["IA-GOV-2021-12-16-43-counties"]["event_description"])

    def test_left_out_releases(self):
        urls = " ".join(r["archive_record_url"] for r in csv_rows("manual_declarations.csv"))
        for word in ("extends", "building-collapse", "covid", "signs-disaster-emergency-proclamation"):
            self.assertNotIn(word, urls)

    def test_each_has_a_reviewed_hazard_and_event_date(self):
        signed = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        overrides = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv")}
        self.assertEqual(set(signed), set(overrides))
        for did, row in overrides.items():
            allowed = {"severe_storm", "wind", "flood"} | ({"winter"} if signed[did] < "2020-03-01" else set())
            self.assertLessEqual(set(row["hazard_category_override"].split(",")), allowed, did)
            if row["event_date"]:
                self.assertLessEqual(row["event_date"], signed[did], did)
                self.assertEqual(row["event_date"][:4], signed[did][:4], did)
        self.assertEqual(overrides["IA-GOV-2020-08-14-cass-guthrie"]["event_date"], "2020-08-10")
        self.assertEqual(overrides["IA-GOV-2023-04-24-10-counties"]["hazard_category_override"], "flood")


class NewsCoverageRowTests(unittest.TestCase):
    def test_rows_span_2000_to_2019_within_their_governors_term(self):
        rows = news_rows()
        self.assertEqual(len(rows), 26)
        ids = [r["declaration_id"] for r in csv_rows("manual_declarations.csv")]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            day = row["date_signed"]
            self.assertTrue("2000-01-01" <= day < "2020-03-01", row["declaration_id"])
            self.assertTrue(row["declaration_id"].startswith("IA-GOV-" + day + "-"), row["declaration_id"])
            self.assertIn(row["governor"], TERMS, row["declaration_id"])
            start, end = TERMS[row["governor"]]
            self.assertTrue(start <= day < end, row["declaration_id"])
            self.assertEqual(row["eo_number"], "")

    def test_radio_iowa_rows_link_a_story_from_the_signing_day_or_the_day_after(self):
        for row in news_rows():
            found = RADIO_IOWA.fullmatch(row["archive_record_url"])
            if not found:
                continue
            story = "-".join(found.groups())
            gap = (date.fromisoformat(story) - date.fromisoformat(row["date_signed"])).days
            self.assertIn(gap, (0, 1), row["declaration_id"])

    def test_notes_quote_the_source_and_say_when_dated_by_the_report(self):
        signed = {r["declaration_id"]: r for r in news_rows()}
        notes = {r["declaration_id"]: r for r in csv_rows("hazard_overrides.csv") if r["declaration_id"] in signed}
        self.assertEqual(set(notes), set(signed))
        for did, note in notes.items():
            self.assertEqual(note["source_url"], signed[did]["archive_record_url"], did)
            self.assertIn("'", note["review_note"], did)
            if "does not give the day" in note["review_note"]:
                self.assertIn(REPORT_DATED, note["review_note"], did)
                found = RADIO_IOWA.fullmatch(signed[did]["archive_record_url"])
                if found:
                    self.assertEqual("-".join(found.groups()), signed[did]["date_signed"], did)

    def test_every_row_names_a_hazard_the_storm_join_reads(self):
        spec = importlib.util.spec_from_file_location("ia_storm_join", HERE / "eo_storm_join.py")
        join = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(join)
        for row in news_rows():
            self.assertTrue(join.compatible_event_types(row["event_description"]), row["declaration_id"])

    def test_no_row_is_an_extension_or_non_weather(self):
        for row in news_rows():
            self.assertNotRegex(row["event_description"],
                                r"(?i)\b(?:extend|extension|amend|rescind|covid|avian|harvest|fuel|propane)")


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest_and_starts_in_2000(self):
        spec = importlib.util.spec_from_file_location("iowa_adapter", HERE / "iowa.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "IA"))
        self.assertTrue(re.match(r"2000-present", note))
        self.assertIn(f"plus {len(news_rows())} from 2000-2019", note)


if __name__ == "__main__":
    unittest.main()
