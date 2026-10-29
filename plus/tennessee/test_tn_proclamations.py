"""Tests for tn_proclamations.py and the join rows it gives tn_eo_scraper.py.

    cd plus/tennessee && python -m unittest test_tn_proclamations
"""
import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

import pandas as pd
import requests

import eo_storm_join
import tn_eo_scraper as tn
import tn_proclamations as procs

# The index as read on October 28, 2026: Title | Governor | Date Signed.
PAGE_ONE = """<table><thead><tr><th>Title</th><th>Governor</th><th>Date Signed</th></tr></thead><tbody>
<tr><td><a href="files/2706.pdf">National Preparedness Month September 2024</a></td><td>Bill Lee</td><td>08-21-2024</td></tr>
<tr><td><a href="files/2700.pdf">State of Emergency May 8, 2024</a></td><td>Bill Lee</td><td>08-14-2024</td></tr>
</tbody></table>"""
PAGE_TWO = """<table><tbody>
<tr><td><a href="/publications/proclamations/files/2650.pdf">State of Emergency March 31 - April 1, 2023</a></td><td>Bill Lee</td><td>06-01-2023</td></tr>
<tr><td>State of Emergency January 2, 2023</td><td>Bill Lee</td><td>02-01-2023</td></tr>
</tbody></table>"""
PDF_TEXT = {"https://tnsos.net/publications/proclamations/files/2700.pdf":
            "severe weather on May 8, 2024, including tornadoes, thunderstorms, and heavy rainfall ... flooding",
            "https://tnsos.net/publications/proclamations/files/2650.pdf": ""}


class IndexTests(unittest.TestCase):
    def test_rows_are_read_with_their_signed_date_and_pdf(self):
        rows = procs.parse_index(PAGE_ONE)
        self.assertEqual([(r["title"], r["signed"]) for r in rows],
                         [("National Preparedness Month September 2024", "2024-08-21"),
                          ("State of Emergency May 8, 2024", "2024-08-14")])
        self.assertEqual(rows[1]["url"], "https://tnsos.net/publications/proclamations/files/2700.pdf")

    def test_the_title_gives_the_event_date(self):
        self.assertEqual(procs.event_date("State of Emergency May 8, 2024"), "2024-05-08")
        self.assertEqual(procs.event_date("State of Emergency March 31 - April 1, 2023"), "2023-03-31")
        self.assertEqual(procs.event_date("State of Emergency"), "")

    def test_pages_are_read_until_one_adds_nothing(self):
        pages = {None: PAGE_ONE, 2: PAGE_TWO, 3: PAGE_TWO}
        calls = []
        def get(url, params=None):
            calls.append(params)
            return pages[(params or {}).get("page")]
        with redirect_stdout(io.StringIO()):
            rows = procs.collect_index(get)
        self.assertEqual(len(rows), 4)
        self.assertEqual(calls, [None, {"page": 2}, {"page": 3}])

    def test_a_missing_first_page_fails_and_a_missing_later_page_ends_the_walk(self):
        def broken(url, params=None):
            if params:
                raise requests.HTTPError("404")
            return PAGE_ONE
        with redirect_stdout(io.StringIO()):
            self.assertEqual(len(procs.collect_index(broken)), 2)
        def down(url, params=None):
            raise requests.HTTPError("503")
        with self.assertRaises(requests.HTTPError):
            procs.collect_index(down)


class EmergencyTests(unittest.TestCase):
    def emergencies(self):
        rows = procs.parse_index(PAGE_ONE) + procs.parse_index(PAGE_TWO)
        with redirect_stdout(io.StringIO()):
            return procs.emergencies(rows, tn.HAZARD_RE, read=lambda url: PDF_TEXT.get(url, ""))

    def test_only_state_of_emergency_titles_are_kept_with_hazards_from_the_pdf(self):
        found = {e["declaration_id"]: e for e in self.emergencies()}
        self.assertEqual(sorted(found), ["TN-PROC-2023-02-01", "TN-PROC-2650", "TN-PROC-2700"])
        may = found["TN-PROC-2700"]
        self.assertEqual((may["signed"], may["event_date"], may["governor"]), ("2024-08-14", "2024-05-08", "Bill Lee"))
        self.assertEqual(may["hazards"], ["flooding", "rainfall", "severe weather", "thunderstorms", "tornadoes"])
        self.assertEqual(found["TN-PROC-2650"]["hazards"], [])            # unreadable PDF
        self.assertEqual(found["TN-PROC-2023-02-01"]["hazards"], [])      # no PDF link

    def test_only_a_proclamation_naming_a_hazard_reaches_the_join_with_its_event_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tn.write_outputs([], root / "a.csv", root / "r.csv", root / "j.csv", self.emergencies())
            with open(root / "j.csv", encoding="utf-8") as handle:
                joined = list(csv.DictReader(handle))
            with open(root / "a.csv", encoding="utf-8") as handle:
                actions = {r["declaration_id"]: r for r in csv.DictReader(handle)}
        self.assertEqual([(r["declaration_id"], r["date_signed"], r["event_date"]) for r in joined],
                         [("TN-PROC-2700", "2024-08-14", "2024-05-08")])
        self.assertEqual(joined[0]["event_description"],
                         "State of Emergency May 8, 2024 (flooding, rainfall, severe weather, thunderstorms, tornadoes)")
        self.assertEqual(actions["TN-PROC-2650"]["weather_related"], "false")
        self.assertEqual(len(actions), 3)

    def test_the_proclamations_failing_does_not_fail_the_orders(self):
        with mock.patch.object(procs, "collect_index", side_effect=requests.ConnectionError("down")), \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(tn.collect_proclamations(), [])
        self.assertIn("Tennessee proclamations not read this run", err.getvalue())


class StormJoinTests(unittest.TestCase):
    def test_the_storm_search_centers_on_the_event_date_and_a_review_still_wins(self):
        declarations = pd.DataFrame([
            {"declaration_id": "TN-PROC-2700", "date_signed": "2024-08-14", "event_date": "2024-05-08"},
            {"declaration_id": "TN-PROC-9", "date_signed": "2024-08-14", "event_date": "2024-05-08"},
            {"declaration_id": "TN-EO-1", "date_signed": "2024-01-01", "event_date": float("nan")},
        ])
        overrides = pd.DataFrame([{"declaration_id": "TN-PROC-9", "hazard_category_override": "flood",
                                   "review_note": "", "source_url": "", "event_date": "2024-05-09"}])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            merged = eo_storm_join.apply_overrides(declarations, overrides)
        dates = dict(zip(merged["declaration_id"], merged["override_event_date"]))
        self.assertEqual(dates, {"TN-PROC-2700": "2024-05-08", "TN-PROC-9": "2024-05-09", "TN-EO-1": ""})


if __name__ == "__main__":
    unittest.main()
