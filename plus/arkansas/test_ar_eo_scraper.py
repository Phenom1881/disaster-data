import csv, tempfile, unittest
import ar_eo_scraper as ar

def post(title,text,date="2024-08-17T12:00:00",ident=1):
    return {"id":ident,"date":date,"link":f"https://governor.arkansas.gov/executive_orders/{ident}/","title":{"rendered":title},"content":{"rendered":text}}

class ArkansasTests(unittest.TestCase):
    def test_official_text_drives_hazard_and_date(self):
        action=ar.parse_post(post("DR 24-06: Emergency declaration for severe thunderstorms and strong winds","I do hereby declare that a state of emergency exists. IN TESTIMONY on this 17 th day of August, 2024."))
        self.assertEqual(action.date,"2024-08-17"); self.assertEqual(ar.classify(action),"declaration")
        with tempfile.TemporaryDirectory() as root:
            paths=[root+f"/{n}.csv" for n in ("actions","rels","join")]; ar.write_outputs([action],*paths)
            with open(paths[2],encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1); self.assertEqual(list(rows[0]),list(ar.JOIN_FIELDS))
    def test_amendment_excluded(self):
        action=ar.parse_post(post("EO 25-03: Executive order amending DR 24-05","Severe storms and tornadoes."))
        self.assertEqual(ar.classify(action),"amendment")
    def test_statute_as_amended_is_not_an_amendment_order(self):
        action=ar.parse_post(post("EO 25-07: Executive order to provide funding as authorized by Ark. Code Ann. 12-75-114, as amended","Severe storms, tornadoes, and flooding are expected. I do hereby declare a state of emergency."))
        self.assertEqual(ar.classify(action),"declaration")
    def test_operational_companion_reference_is_not_declaration(self):
        action=ar.parse_post(post("Executive order to suspend certain requirements for FEMA housing unit transport","Executive Order 23-20 declared a state of emergency after severe thunderstorms and tornadoes."))
        self.assertTrue(action.number.startswith("POST-")); self.assertEqual(ar.classify(action),"administrative")
    def test_no_overrides(self): self.assertEqual(ar.HAZARD_OVERRIDES,{})


import json
import os
import re
import subprocess
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent

# Governors of Arkansas and the day each took office.
GOVERNOR_TERMS = (("2023-01-10", "Sarah Huckabee Sanders"), ("2015-01-13", "Asa Hutchinson"),
                  ("2007-01-09", "Mike Beebe"), ("1996-07-15", "Mike Huckabee"))


def governor_on(day):
    return next(name for start, name in GOVERNOR_TERMS if day >= start)


def csv_rows(name):
    with open(HERE / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class CoverageNoteTests(unittest.TestCase):
    def test_refresh_note_matches_the_manifest(self):
        """A refresh (build-plus.py --collect) shows the note collect()
        returns, and a build without collection shows the manifest's."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("arkansas_adapter", HERE / "arkansas.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(adapter.subprocess, "run", return_value=done):
            _, note = adapter.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((HERE.parents[1] / "scripts" / "plus" / "state-manifest.json").read_text())
        self.assertEqual(note, next(st["coverage_note"] for st in manifest["states"] if st["abbreviation"] == "AR"))
        self.assertTrue(note.startswith("2000-present"))


class HandAddedDeclarationTests(unittest.TestCase):
    """manual_declarations.csv carries the weather declarations from before
    the current Governor's archive. Each is dated from the State Library's
    catalog of DR proclamations or a dated news report."""

    def test_dates_read_from_the_sources(self):
        dates = {r["declaration_id"]: r["date_signed"] for r in csv_rows("manual_declarations.csv")}
        expected = {
            # State Library: each 2010 amendment names the original and its date.
            "AR-DR-06-22": "2006-08-06", "AR-DR-08-07": "2008-03-20", "AR-DR-08-31": "2008-09-08",
            "AR-DR-08-37": "2008-09-22", "AR-DR-09-03": "2009-01-27", "AR-DR-09-12": "2009-04-10",
            "AR-DR-09-17": "2009-05-13", "AR-DR-09-35": "2009-10-20", "AR-DR-21-17": "2021-12-11",
            "AR-SOE-2011-02-01": "2011-02-01",
            # Dated news reports.
            "AR-SOE-2009-11-07": "2009-11-07", "AR-SOE-2011-01-01": "2011-01-01",
            "AR-SOE-2013-08-16": "2013-08-16", "AR-SOE-2015-12-29": "2015-12-29",
            "AR-SOE-2016-03-10": "2016-03-10", "AR-SOE-2017-04-30": "2017-04-30",
            "AR-SOE-2020-03-29": "2020-03-29", "AR-SOE-2020-04-24": "2020-04-24",
            "AR-SOE-2020-08-26": "2020-08-26", "AR-SOE-2021-06-10": "2021-06-10",
        }
        self.assertEqual({k: dates.get(k) for k in expected}, expected)

    def test_ids_are_unique_and_carry_the_date_or_number(self):
        rows = csv_rows("manual_declarations.csv")
        ids = [r["declaration_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            did, day = row["declaration_id"], row["date_signed"]
            if did.startswith("AR-SOE-"):
                self.assertEqual(did, "AR-SOE-" + day)
            else:
                match = re.fullmatch(r"AR-DR-(\d\d)-(\d\d)", did)
                self.assertTrue(match, did)
                self.assertEqual(row["eo_number"], "DR %s-%s" % match.groups(), did)
                self.assertEqual(day[2:4], match.group(1), did)

    def test_governor_in_office_on_each_date(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertEqual(row["governor"], governor_on(row["date_signed"]), row["declaration_id"])

    def test_each_names_its_weather_hazard_and_links_its_source(self):
        for row in csv_rows("manual_declarations.csv"):
            self.assertRegex(row["event_description"].lower(),
                             r"storm|flood|tornado|ice|snow|sleet|winter|hurricane|wind", row["declaration_id"])
            self.assertTrue(row["archive_record_url"].startswith("https://"), row["declaration_id"])

    def test_reviewed_event_dates_come_before_signing(self):
        signed = {r["declaration_id"]: r["date_signed"]
                  for name in ("manual_declarations.csv", "declarations_for_join.csv") for r in csv_rows(name)}
        for row in csv_rows("hazard_overrides.csv"):
            self.assertIn(row["declaration_id"], signed)
            if row["event_date"]:
                self.assertLessEqual(row["event_date"], signed[row["declaration_id"]], row["declaration_id"])
        events = {r["declaration_id"]: r["event_date"] for r in csv_rows("hazard_overrides.csv")}
        self.assertEqual(events["AR-DR-06-22"], "2006-04-02")
        self.assertEqual(events["AR-SOE-2020-04-24"], "2020-04-12")


if __name__=="__main__": unittest.main()
