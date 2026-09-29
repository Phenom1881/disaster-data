"""Tests for scripts/plus_fmcsa.py and its use in build-plus.py. Offline:
the archive pages are fixtures shaped like FMCSA's.

    cd scripts && python -m unittest test_plus_fmcsa
"""
import csv
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ["PLUS_RETRY_DELAY"] = "0"
HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("plus_fmcsa", str(HERE / "plus_fmcsa.py"))
fm = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("plus_fmcsa", fm)
_SPEC.loader.exec_module(fm)
_BP = importlib.util.spec_from_file_location("build_plus", str(HERE / "build-plus.py"))
bp = importlib.util.module_from_spec(_BP)
sys.modules.setdefault("build_plus", bp)
_BP.loader.exec_module(bp)


def entry(title, href, effective):
    return (f'<p><strong>Description:</strong> <a href="{href}">{title}</a></p>'
            f'<p><strong>Effective:</strong> {effective}</p><p><strong>Expires on:</strong> TBD</p>')


PAGE_2023 = ("<html><body><nav><a href='/emergency/nav-link'>Nav</a></nav><main>"
             "<h2>Federal Emergency Declarations by FMCSA</h2>"
             + entry("WSC-MSC - Regional Emergency Declaration (No. 2023-001)", "/emergency/wsc-msc-2023-001", "01/02/2023")
             + "<h2>State Emergency Declarations</h2><h3>Maine</h3>"
             + entry("Maine Proclamation of Emergency for Hurricane Lee", "/emergency/maine-proclamation-emergency-hurricane-lee", "09/14/2023")
             + "<h3>Nevada</h3>"
             + entry("Nevada Proclamation Declaring a Severe Weather Emergency 8-20-2023", "/emergency/nevada-severe-weather", "08/20/2023")
             + entry("Proclamation of the Clark County Manager Declaring a State of Emergency", "/emergency/clark-county", "08/20/2023")
             + entry("Nevada Emergency due to Gas Pipeline Disruption 02102023", "/emergency/nevada-gas", "02/10/2023")
             + entry("State of Nevada - DECLARATION OF EMERGENCY - EXTENSION", "/emergency/nevada-extension", "01/22/2023")
             + "<h3>Vermont</h3>"
             + entry("Vermont Emergency Declaration", "/emergency/vermont-emergency-declaration-070923-0", "07/09/3023")
             + "</main></body></html>")
VERMONT_PAGE = ("<html><body><main><h1>Vermont Emergency Declaration</h1><p>Governor Scott declared a state of "
                "emergency on July 9, 2023 in response to severe flooding from heavy rainfall across the state.</p>"
                "</main></body></html>")
BASE = "https://www.fmcsa.dot.gov"


class ParseTests(unittest.TestCase):
    def test_state_entries_titles_and_dates(self):
        rows = {r["title"]: r for r in fm.parse_archive_page(PAGE_2023, BASE + "/emergency/archive-2023", 2023)}
        self.assertEqual(rows["Maine Proclamation of Emergency for Hurricane Lee"]["state"], "Maine")
        self.assertEqual(rows["Maine Proclamation of Emergency for Hurricane Lee"]["effective"], "2023-09-14")
        self.assertEqual(rows["Vermont Emergency Declaration"]["effective"], "2023-07-09")   # "3023" typo
        self.assertEqual(rows["Proclamation of the Clark County Manager Declaring a State of Emergency"]["state"],
                         "Nevada")                                                          # from the heading
        self.assertNotIn("WSC-MSC - Regional Emergency Declaration (No. 2023-001)", rows)   # before the state section
        self.assertNotIn("Nav", rows)

    def test_west_virginia_is_not_virginia(self):
        self.assertEqual(fm.STATE_RE.match("West Virginia Declaration of Emergency").group(1), "West Virginia")


class RefreshAndSupplementTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="fmcsa_"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def site(self, broken=False):
        self.requested = []

        def get(url):
            self.requested.append(url)
            if broken:
                raise OSError("refused")
            if url.endswith("vermont-emergency-declaration-070923-0"):
                return VERMONT_PAGE
            if url.endswith("-2023"):
                return PAGE_2023
            return "<html><body></body></html>"
        return get

    def refreshed(self):
        note = fm.refresh(self.root, get=self.site(), today=date(2026, 9, 28))
        return note, fm.load_entries(self.root / "plus" / "_fmcsa" / "entries.csv")

    def test_untitled_declarations_get_a_hazard_sentence_once(self):
        note, entries = self.refreshed()
        vermont = next(e for e in entries.values() if e["state"] == "Vermont")
        self.assertIn("severe flooding", vermont["hazard_text"])
        self.assertIn("1 declaration page(s) read", note)
        fm.refresh(self.root, get=self.site(), today=date(2026, 9, 28))
        self.assertNotIn(BASE + "/emergency/vermont-emergency-declaration-070923-0", self.requested)

    def test_failure_keeps_the_saved_entries(self):
        _, before = self.refreshed()
        note = fm.refresh(self.root, get=self.site(broken=True), today=date(2026, 9, 28))
        self.assertIn("pages not read", note)
        self.assertEqual(fm.load_entries(self.root / "plus" / "_fmcsa" / "entries.csv").keys(), before.keys())

    def test_only_new_statewide_weather_declarations_are_supplied(self):
        _, entries = self.refreshed()
        nevada = fm.supplement_rows({"name": "Nevada", "abbreviation": "NV"}, [], entries)
        self.assertEqual([r["event_description"] for r in nevada],
                         ["Nevada Proclamation Declaring a Severe Weather Emergency 8-20-2023"])
        vermont = fm.supplement_rows({"name": "Vermont", "abbreviation": "VT"}, [], entries)
        self.assertTrue(vermont[0]["event_description"].startswith("Vermont Emergency Declaration. From FMCSA's copy:"))
        self.assertTrue(fm.hazard_types(vermont[0]["event_description"]))
        # Already in the state's own source (two days apart): left out.
        self.assertEqual(fm.supplement_rows({"name": "Maine", "abbreviation": "ME"},
                                            [{"date_signed": "2023-09-16"}], entries), [])


class BuilderTests(unittest.TestCase):
    def test_supplement_is_shown_joined_and_kept_apart_from_the_state_source(self):
        root = Path(tempfile.mkdtemp(prefix="fmcsa_build_"))
        try:
            state = {"name": "Vermont", "abbreviation": "VT", "slug": "vermont", "adapter_status": "implemented",
                     "adapter_file": "vermont.py", "action_files": ["declarations_for_join.csv"],
                     "fmcsa_supplement": True}
            folder = root / "plus" / "vermont"
            folder.mkdir(parents=True)
            (folder / "declarations_for_join.csv").write_text(
                "declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
                "VT-EO-01-24,Phil Scott,01-24,Flooding,2024-07-11,https://x\n")
            fm.refresh(root, get=lambda url: VERMONT_PAGE if url.endswith("070923-0")
                       else PAGE_2023 if url.endswith("-2023") else "<html></html>", today=date(2026, 9, 28))
            summary = bp.process_state(state, root, collect=False, join_storms=False, dry_run=False)
            self.assertEqual(summary["metrics"]["action_count"], 2)
            self.assertIn("plus 1 weather declaration from FMCSA", summary["coverage"])
            with (folder / "declarations_for_join.csv").open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)        # the state's own file is untouched
            combined = bp.with_fmcsa_supplement(folder / "declarations_for_join.csv", folder)
            with combined.open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)
            state["fmcsa_supplement"] = False
            bp.process_state(state, root, collect=False, join_storms=False, dry_run=False)
            self.assertFalse((folder / "fmcsa_declarations.csv").exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
