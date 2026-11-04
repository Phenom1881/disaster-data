"""Tests for the Declaration Tracker (scripts/declaration_tracker.py).

The tracker reads the "Declaration Requests in Process" table out of archived
FEMA Daily Operations Briefings, folds the daily rows into one record per
request, and checks each request against OpenFEMA. These tests use small
hand-built pages and a hand-built FEMA snapshot, so they need no network and
no PDFs.

Run:  python -m unittest scripts/test_declaration_tracker.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import declaration_tracker as dt  # noqa: E402

EN = "\u2013"  # the briefing separates fields with an en dash

HEADER = ("  State / Tribe / Territory  " + EN + " Incident Description"
          + " " * 60 + "Type      IA      PA     HM      Requested")


def col(header, name):
    return header.index(name)


def row(desc, typ, programs, requested, header=HEADER):
    """A table row laid out under HEADER the way pypdf's layout mode prints it."""
    line = list(" " + desc)
    line += [" "] * (col(header, "Type") - len(line))
    line += list(typ)
    for name in ("IA", "PA", "HM"):
        if name in programs:
            line += [" "] * (col(header, name) - len(line))
            line += ["X"]
    if requested:
        line += [" "] * (col(header, "Requested") - len(line))
        line += list(requested)
    return "".join(line)


def page(rows, title="Declaration Requests in Process " + EN + " 3", footnotes=""):
    return "\n".join(["", title, "", HEADER] + rows + ["", footnotes, "", "National Watch Center"])


def brief(day, rows=None, has_table=True):
    return {"date": day, "has_table": has_table, "rows": rows or []}


def parsed(day, *lines, footnotes=""):
    return dt.parse_page(page(list(lines), footnotes=footnotes), day)


class ParsePageTests(unittest.TestCase):
    def test_page_without_the_table_returns_none(self):
        self.assertIsNone(dt.parse_page("National Watch Center\nSevere Weather Outlook", "2026-10-29"))

    def test_reads_requester_type_programs_and_date(self):
        rows = parsed("2026-10-29", row("IN " + EN + " Severe Storms and Flooding", "DR", "IA PA HM", "Aug 6"),
                      row("NJ " + EN + " Severe Storms", "DR", "PA HM", "Oct 26"))
        self.assertEqual([(r["state"], r["type"], r["programs"], r["requested"]) for r in rows],
                         [("IN", "DR", ["IA", "PA", "HM"], "2026-08-06"),
                          ("NJ", "DR", ["PA", "HM"], "2026-10-26")])
        self.assertEqual(rows[0]["incident"], "Severe Storms and Flooding")

    def test_an_x_outside_the_program_columns_is_ignored(self):
        wide = HEADER.replace("HM      Requested", "HM" + " " * 30 + "Requested")
        line = list(row("KS " + EN + " Severe Storms", "DR", "PA", "Sep 15", header=wide))
        line[col(wide, "HM") + 15] = "X"
        text = page([]).replace(HEADER, wide).replace("\nNational Watch", "".join(line) + "\nNational Watch")
        rows = dt.parse_page(text, "2026-10-29")
        self.assertEqual(rows[0]["programs"], ["PA"])

    def test_appeal_and_status_tags_come_off_the_incident(self):
        rows = parsed("2026-09-03",
                      row("MA " + EN + " Severe Winter Storm " + EN + " Appeal " + EN + " Denied", "DR", "PA", ""),
                      row("HI - Hurricane Lala - APPROVED", "EM", "PA", ""))
        self.assertEqual((rows[0]["appeal"], rows[0]["status"], rows[0]["incident"]),
                         (True, "denied", "Severe Winter Storm"))
        self.assertEqual((rows[1]["appeal"], rows[1]["status"], rows[1]["incident"]),
                         (False, "approved", "Hurricane Lala"))
        self.assertIsNone(rows[0]["requested"])

    def test_tribal_codes_are_named_from_the_footnotes(self):
        rows = parsed("2026-10-29",
                      row("RST1 " + EN + " Severe Storms", "DR", "IA PA HM", "Sep 29"),
                      row("CTBYN2 " + EN + " Wildfires", "DR", "IA PA HM", "Oct 1"),
                      row("OST* " + EN + " Flooding", "DR", "PA", "Jul 29"),
                      footnotes="1 Rosebud Sioux Tribe, 2 Confederated Tribes and Bands of the Yakama Nation\n"
                                "*Oglala Sioux Tribe")
        self.assertEqual([(r["tribe"], r["state"]) for r in rows],
                         [("Rosebud Sioux Tribe", "SD"),
                          ("Confederated Tribes and Bands of the Yakama Nation", "WA"),
                          ("Oglala Sioux Tribe", "SD")])

    def test_territory_codes_map_to_postal_codes(self):
        rows = parsed("2026-10-18", row("CNMI " + EN + " Tropical Storm Champi", "EM", "PA", "Oct 16"))
        self.assertEqual((rows[0]["state"], rows[0]["tribe"]), ("MP", None))

    def test_a_split_month_is_still_read(self):
        rows = parsed("2026-08-21", row("KS " + EN + " Severe Storms", "DR", "PA HM", "Au g 11"))
        self.assertEqual(rows[0]["requested"], "2026-08-11")


class RequestDateTests(unittest.TestCase):
    def test_same_year_as_the_briefing(self):
        self.assertEqual(dt.infer_request_date("Oct", "27", dt.date(2026, 10, 29)), "2026-10-27")

    def test_a_december_request_on_a_january_briefing_is_last_year(self):
        self.assertEqual(dt.infer_request_date("Dec", "24", dt.date(2027, 1, 5)), "2026-12-24")

    def test_a_date_a_few_days_ahead_stays_in_the_briefing_year(self):
        self.assertEqual(dt.infer_request_date("Nov", "2", dt.date(2026, 10, 29)), "2026-11-02")

    def test_impossible_dates_are_dropped(self):
        self.assertIsNone(dt.infer_request_date("Feb", "30", dt.date(2026, 3, 1)))
        self.assertIsNone(dt.infer_request_date("Foo", "3", dt.date(2026, 3, 1)))


def r(day, state, typ, requested, incident="Severe Storms", appeal=False, status=None, tribe=None, programs=None):
    return {"brief": day, "code": state, "state": state, "tribe": tribe, "type": typ, "incident": incident,
            "appeal": appeal, "status": status, "requested": requested, "programs": programs}


class FoldTests(unittest.TestCase):
    def test_daily_rows_become_one_request(self):
        briefs = {f"{d}.pdf": brief(d, [r(d, "IN", "DR", "2026-08-06", programs=["PA"])])
                  for d in ("2026-10-27", "2026-10-28", "2026-10-29")}
        reqs, last = dt.fold_requests(briefs)
        self.assertEqual(len(reqs), 1)
        self.assertEqual((reqs[0]["first_seen"], reqs[0]["last_seen"], reqs[0]["days_listed"], last),
                         ("2026-10-27", "2026-10-29", 3, "2026-10-29"))
        self.assertEqual(reqs[0]["id"], "in-dr-2026-08-06")

    def test_an_approved_row_without_a_date_joins_its_request(self):
        briefs = {
            "2026-10-26.pdf": brief("2026-10-26", [r("2026-10-26", "NM", "EM", "2026-10-24")]),
            "2026-10-27.pdf": brief("2026-10-27", [r("2026-10-27", "NM", "EM", None, status="approved")]),
        }
        reqs, _ = dt.fold_requests(briefs)
        self.assertEqual(len(reqs), 1)
        self.assertEqual((reqs[0]["brief_status"], reqs[0]["brief_status_date"]), ("approved", "2026-10-27"))

    def test_same_state_different_requests_stay_apart(self):
        rows = [r("2026-10-29", "NE", "DR", "2026-08-31", appeal=True, incident="Severe Storm and Flooding"),
                r("2026-10-29", "NE", "DR", "2026-10-26", incident="Severe Storms and Flooding")]
        reqs, _ = dt.fold_requests({"2026-10-29.pdf": brief("2026-10-29", rows)})
        self.assertEqual(sorted(q["id"] for q in reqs), ["ne-dr-2026-08-31-appeal", "ne-dr-2026-10-26"])

    def test_a_date_corrected_midway_is_one_request(self):
        briefs = {
            "2026-10-08.pdf": brief("2026-10-08", [r("2026-10-08", "WA", "DR", "2026-10-02", incident="Wildfires")]),
            "2026-10-09.pdf": brief("2026-10-09", [r("2026-10-09", "WA", "DR", "2026-09-25", incident="Wildfires")]),
        }
        reqs, _ = dt.fold_requests(briefs)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["requested"], "2026-09-25")


def decl(fid, state, typ, day, title, tribal=False):
    return {"femaDeclarationString": fid, "state": state, "declarationType": typ,
            "declarationDate": day + "T00:00:00.000Z", "declarationTitle": title, "tribalRequest": tribal}


def denial(num, state, requested, decided, typ="Major Disaster", name="Severe Storms", tribal=False):
    return {"declarationRequestNumber": num, "stateAbbreviation": state, "tribalRequest": tribal,
            "declarationRequestDate": requested + "T00:00:00.000Z", "declarationRequestType": typ,
            "incidentName": name, "currentRequestStatus": "Turndown",
            "requestStatusDate": decided + "T00:00:00.000Z"}


TABLE_DAYS = ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-28", "2026-10-29"]


def ledger(rows_by_day, fema, today="2026-11-04"):
    briefs = {f"{d}.pdf": brief(d, rows_by_day.get(d, [])) for d in TABLE_DAYS}
    reqs, _ = dt.fold_requests(briefs)
    dt.resolve(reqs, fema, TABLE_DAYS, today)
    return {q["id"]: q for q in reqs}


class ResolveTests(unittest.TestCase):
    def test_declared_request_gets_the_declaration_and_its_wait(self):
        rows = {"2026-10-07": [r("2026-10-07", "WI", "DR", "2026-08-26", incident="Severe Storms and Tornado")],
                "2026-10-08": [r("2026-10-08", "WI", "DR", None, status="approved", incident="Severe Storms and Tornado")]}
        got = ledger(rows, {"declarations": [decl("DR-4949-WI", "WI", "DR", "2026-10-07", "SEVERE STORMS AND TORNADOES")]})
        q = got["wi-dr-2026-08-26"]
        self.assertEqual((q["status"], q["declaration"]["id"], q["decision_date"], q["days"]),
                         ("declared", "DR-4949-WI", "2026-10-07", 42))

    def test_a_declaration_is_never_given_to_two_requests(self):
        rows = {"2026-10-07": [r("2026-10-07", "HI", "DR", "2026-09-08", incident="Hurricane Lala"),
                               r("2026-10-07", "HI", "DR", "2026-09-09", incident="Hurricane Lowell")]}
        fema = {"declarations": [decl("DR-4951-HI", "HI", "DR", "2026-10-07", "HURRICANE LALA"),
                                 decl("DR-4952-HI", "HI", "DR", "2026-10-07", "HURRICANE LOWELL")]}
        got = ledger(rows, fema)
        self.assertEqual(got["hi-dr-2026-09-08"]["declaration"]["id"], "DR-4951-HI")
        self.assertEqual(got["hi-dr-2026-09-09"]["declaration"]["id"], "DR-4952-HI")

    def test_one_declaration_for_two_identical_requests_closes_only_one(self):
        rows = {"2026-10-29": [r("2026-10-29", "WA", "DR", "2026-10-02", incident="Wildfires"),
                               r("2026-10-29", "WA", "DR", "2026-10-20", incident="Wildfires")]}
        got = ledger(rows, {"declarations": [decl("DR-4960-WA", "WA", "DR", "2026-11-02", "WILDFIRES")]})
        self.assertEqual(sorted(q["status"] for q in got.values()), ["declared", "open"])

    def test_a_declaration_before_the_request_does_not_count(self):
        rows = {"2026-10-29": [r("2026-10-29", "FL", "DR", "2026-10-28", incident="Hurricane Isaias")]}
        got = ledger(rows, {"declarations": [decl("DR-4955-FL", "FL", "DR", "2026-10-27", "HURRICANE ISAIAS")]})
        self.assertEqual(got["fl-dr-2026-10-28"]["status"], "open")

    def test_a_state_declaration_is_not_given_to_a_tribe(self):
        rows = {"2026-10-29": [r("2026-10-29", "SD", "DR", "2026-09-29", tribe="Rosebud Sioux Tribe")]}
        got = ledger(rows, {"declarations": [decl("DR-4960-SD", "SD", "DR", "2026-11-02", "SEVERE STORMS")]})
        self.assertEqual(got["rosebud-sioux-tribe-dr-2026-09-29"]["status"], "open")

    def test_turndown_matched_on_request_date(self):
        rows = {"2026-10-07": [r("2026-10-07", "IL", "DR", "2026-09-15")]}
        got = ledger(rows, {"denials": [denial(26158, "IL", "2026-09-15", "2026-10-07")]})
        q = got["il-dr-2026-09-15"]
        self.assertEqual((q["status"], q["denial_number"], q["decision_date"], q["days"]),
                         ("turned_down", 26158, "2026-10-07", 22))

    def test_turndown_of_another_type_does_not_match(self):
        rows = {"2026-10-29": [r("2026-10-29", "IL", "EM", "2026-09-15")]}
        got = ledger(rows, {"denials": [denial(26158, "IL", "2026-09-15", "2026-10-07")]})
        self.assertEqual(got["il-em-2026-09-15"]["status"], "open")

    def test_denied_appeal_matched_on_decision_date(self):
        rows = {"2026-10-07": [r("2026-10-07", "WV", "DR", "2026-08-31", appeal=True)],
                "2026-10-08": [r("2026-10-08", "WV", "DR", None, appeal=True, status="denied")]}
        got = ledger(rows, {"denials": [denial(26100, "WV", "2026-07-21", "2026-10-07")]})
        self.assertEqual(got["wv-dr-2026-08-31-appeal"]["denial_number"], 26100)

    def test_brief_said_denied_but_fema_has_nothing_yet(self):
        rows = {"2026-10-08": [r("2026-10-08", "ID", "DR", "2026-07-22", status="denied")]}
        q = ledger(rows, {})["id-dr-2026-07-22"]
        self.assertEqual((q["status"], q["decision_date"]), ("denied_per_brief", "2026-10-08"))

    def test_still_on_the_last_table_is_open_and_counts_to_today(self):
        rows = {"2026-10-29": [r("2026-10-29", "IN", "DR", "2026-08-06")]}
        q = ledger(rows, {}, today="2026-11-04")["in-dr-2026-08-06"]
        self.assertEqual((q["status"], q["days"]), ("open", 90))

    def test_dropped_off_without_an_outcome(self):
        rows = {"2026-10-06": [r("2026-10-06", "NE", "DR", "2026-09-15")]}
        q = ledger(rows, {})["ne-dr-2026-09-15"]
        self.assertEqual((q["status"], q["days"]), ("left_brief", 21))


class BuildTests(unittest.TestCase):
    def test_build_uses_the_snapshot_and_never_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ops-briefings"
            out.mkdir()
            old = (dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH)
            dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = out, out / "t.json", out / "c.json"
            fetch = dt.fetch_fema
            dt.fetch_fema = lambda since: self.fail("network used")
            try:
                ledger = dt.build(today="2026-11-04", fema_override={"declarations": [], "denials": []})
                dt.write(ledger)
            finally:
                dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = old
                dt.fetch_fema = fetch
            data = json.loads((out / "t.json").read_text(encoding="utf-8"))
            self.assertTrue(data["unofficial"])
            self.assertEqual(data["requests"], [])
            self.assertNotIn("_cache", data)

    def test_unreachable_fema_keeps_the_last_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            snap = {"declarations": [decl("DR-1-IN", "IN", "DR", "2026-10-30", "SEVERE STORMS")], "denials": []}
            (out / "c.json").write_text(json.dumps({"parser_version": dt.PARSER_VERSION, "briefs": {
                "2026-10-29.pdf": brief("2026-10-29", [r("2026-10-29", "IN", "DR", "2026-08-06")])},
                "fema": snap, "fema_fetched_at": "2026-11-03T14:00:00Z"}), encoding="utf-8")
            (out / "2026-10-29.pdf").write_bytes(b"")
            old = (dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH)
            dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = out, out / "t.json", out / "c.json"
            fetch, env = dt.fetch_fema, os.environ.pop("DD_TRACKER_FEMA_JSON", None)

            def down(since):
                raise ConnectionError("offline")
            dt.fetch_fema = down
            try:
                ledger = dt.build(today="2026-11-04")
            finally:
                dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = old
                dt.fetch_fema = fetch
                if env is not None:
                    os.environ["DD_TRACKER_FEMA_JSON"] = env
            self.assertEqual(ledger["fema_fetched_at"], "2026-11-03T14:00:00Z")
            self.assertIn("could not be reached", ledger["fema_note"])
            self.assertEqual(ledger["requests"][0]["declaration"]["id"], "DR-1-IN")


class WiringTests(unittest.TestCase):
    def test_nav_links_the_page_and_the_page_reads_the_ledger(self):
        nav = (ROOT / "nav.js").read_text(encoding="utf-8")
        self.assertIn('["Declaration Tracker", "/declaration-tracker.html"]', nav)
        html = (ROOT / "declaration-tracker.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/nav.js"></script>', html)
        self.assertIn("fetch('/archive/ops-briefings/declaration-tracker.json'", html)
        self.assertEqual(dt.LEDGER_PATH.as_posix().split("/")[-2:], ["ops-briefings", "declaration-tracker.json"])

    def test_the_daily_job_can_still_find_its_two_scripts(self):
        # ops-briefing.yml finds its scripts with `find scripts -iname ... | head -n1`;
        # nothing new may match those patterns ahead of the real scripts.
        import fnmatch
        names = [p.name.lower() for p in HERE.iterdir()]
        self.assertEqual([n for n in names if fnmatch.fnmatch(n, "build*ops*pages*.py")], ["build ops pages.py"])
        self.assertEqual([n for n in names if fnmatch.fnmatch(n, "fetch*ops*brief*.py")], ["fetch ops briefing.py"])

    def test_a_tracker_failure_does_not_stop_the_briefing_pages(self):
        spec = importlib.util.spec_from_file_location("build_ops_pages", HERE / "build ops pages.py")
        pages = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pages)
        broken = types.ModuleType("declaration_tracker")

        def boom():
            raise RuntimeError("tracker broke")
        broken.main = boom
        with tempfile.TemporaryDirectory() as tmp:
            cwd, saved = os.getcwd(), sys.modules.get("declaration_tracker")
            sys.modules["declaration_tracker"] = broken
            pages.HISTORY_CSV = Path(tmp) / "none.csv"
            pages.SITE_DIR = Path(tmp) / "ops-briefings"
            pages.ARCHIVE_HUB_DIR = pages.SITE_DIR / "archive"
            try:
                os.chdir(tmp)
                self.assertEqual(pages.main(), 0)
            finally:
                os.chdir(cwd)
                sys.modules["declaration_tracker"] = saved if saved is not None else dt
            self.assertTrue((Path(tmp) / "ops-briefings" / "index.html").exists())

    def test_no_long_dashes(self):
        for path in (HERE / "declaration_tracker.py", ROOT / "declaration-tracker.html", ROOT / "nav.js",
                     HERE / "build ops pages.py", Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text, path.name)
            self.assertNotIn("\u2014", text, path.name)


if __name__ == "__main__":
    unittest.main()
