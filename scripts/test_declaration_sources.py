"""Tests for the Declaration Tracker's official-source links
(scripts/declaration_sources.py).

Every page and feed here is hand-built and every request goes to a fake
session, so the tests never touch the network.

Run:  python -m unittest scripts/test_declaration_sources.py
"""
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
os.environ["DD_TRACKER_SCRAPE"] = "0"  # tests never crawl unless they ask to
import tempfile as _tempfile  # noqa: E402
_SCRATCH = Path(_tempfile.mkdtemp(prefix="tracker-tests-"))
import declaration_sources as ds  # noqa: E402
import declaration_tracker as dt  # noqa: E402
dt.SOURCES_PATH, dt.REVIEW_PATH = _SCRATCH / "declaration-sources.csv", _SCRATCH / "declaration-sources-review.csv"

UA = "DisasterData.IO declaration tracker (+https://www.disasterdata.io/declaration-tracker.html)"


class Resp:
    def __init__(self, text="", status=200, url=None):
        self.text, self.status_code, self.url = text, status, url


class Session:
    """Answers from a dict of url -> Resp (or text). Records what was asked."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, timeout=None, headers=None, allow_redirects=True):
        self.calls.append((url, (headers or {}).get("User-Agent")))
        page = self.pages.get(url)
        if page is None:
            return Resp("", 404, url)
        return page if isinstance(page, Resp) else Resp(page, 200, url)


class Clock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def fetcher(pages, budget=10_000):
    clock = Clock()
    return ds.Fetcher(UA, budget=budget, session=Session(pages), sleep=clock.sleep, clock=clock), clock


def release(title, body, date_line="FOR IMMEDIATE RELEASE: Oct. 29, 2026", related=""):
    return (f"<html><head><title>{title}</title></head><body><nav>Home News Governor declares disaster "
            f"denied approved</nav><main><h1>{title}</h1><p>{date_line}</p><p>{body}</p>"
            f"{related}</main><footer>Contact</footer></body></html>")


def req(rid, state, typ, requested, status="open", appeal=False, decision=None, last_seen="2026-10-29", tribe=None):
    return {"id": rid, "state": state, "type": typ, "requested": requested, "status": status, "appeal": appeal,
            "decision_date": decision, "last_seen": last_seen, "tribe": tribe}


def item(state, action, typ, published, from_title=True, appeal=False):
    return {"state": state, "action": action, "type": typ, "published": published, "from_title": from_title,
            "appeal": appeal}


class ClassifyTests(unittest.TestCase):
    def test_real_request_headlines(self):
        cases = {
            "Governor Kelly requests a declaration of major presidential disaster":
                "Governor Laura Kelly sent a request to FEMA asking for a major presidential disaster declaration.",
            "Gov. Pillen Requests Federal Disaster Declaration for Flood Damaged Counties":
                "Governor Jim Pillen has requested a federal disaster declaration. The request for public assistance applies.",
            "Governor Hochul Requests Major Disaster Declaration to Secure Federal Assistance for Long Island":
                "If Granted, Declaration Would Provide Federal Assistance. Governor Hochul requested a declaration from President Trump.",
        }
        for title, lead in cases.items():
            got = ds.classify(title, lead)
            self.assertEqual((got["action"], got["type"], got["from_title"]), ("request", "DR", True), title)

    def test_a_federal_disaster_declaration_for_public_assistance_is_a_dr(self):
        got = ds.classify("Governor Requests Federal Disaster Declaration",
                          "The governor requested a federal disaster declaration for public assistance.")
        self.assertEqual(got["type"], "DR")
        got = ds.classify("Governor Requests Federal Disaster Declaration", "The governor asked the President for help.")
        self.assertIsNone(got["type"])

    def test_emergency_declarations_are_em(self):
        got = ds.classify("Governor Secures Federal Emergency Declaration Ahead of Hurricane",
                          "President Trump granted the emergency declaration.")
        self.assertEqual((got["action"], got["type"]), ("approved", "EM"))

    def test_both_types_named_leaves_type_open(self):
        got = ds.classify("Governor requests major disaster and emergency declaration",
                          "FEMA will review the major disaster request.")
        self.assertIsNone(got["type"])

    def test_approval_denial_and_appeal(self):
        self.assertEqual(ds.classify("President Trump Approves Governor's Request for Major Disaster Declaration", "")["action"], "approved")
        self.assertEqual(ds.classify("FEMA Denies Governor's Request for Major Disaster Declaration", "")["action"], "denied")
        got = ds.classify("Governor Lee Appeals Denial of Federal Disaster Declaration",
                          "Governor Lee appealed FEMA's denial of the major disaster declaration request.")
        self.assertEqual((got["action"], got["appeal"]), ("request", True))
        self.assertEqual(ds.classify("Governor's Appeal Denied for Major Disaster Declaration", "")["action"], "denied")

    def test_not_federal_declarations_are_left_out(self):
        for title in ("Governor Hochul Requests Physical Disaster Declaration from U.S. Small Business Administration",
                      "Governor Sherrill Requests Disaster Designation from U.S. Department of Agriculture",
                      "Governor Requests USDA Secretarial Disaster Declaration for Drought"):
            self.assertFalse(ds.is_candidate_headline(title), title)
            self.assertIsNone(ds.classify(title, "federal declaration"), title)
        self.assertFalse(ds.is_candidate_headline("Governor Katie Hobbs Declares Statewide State of Emergency"))
        self.assertIsNone(ds.classify("Governor issues disaster declaration for wildland fires",
                                      "Governor Kelly signed a state disaster proclamation."))

    def test_an_earlier_pl_84_99_request_in_the_body_does_not_hide_the_release(self):
        got = ds.classify("Governor Sherrill Requests Major Disaster Declaration and Federal Relief",
                          "This request follows a previous request under Public Law 84-99 to the Army Corps.")
        self.assertEqual(got["action"], "request")

    def test_federal_but_unclear_is_kept_for_review(self):
        got = ds.classify("Governor Kelly Advocates for Federal Disaster Aid",
                          "The governor urged FEMA to act on the pending major disaster declaration.")
        self.assertEqual((got["action"], got["from_title"]), ("unclear", False))

    def test_action_from_the_lead_is_never_from_the_title(self):
        got = ds.classify("Statement on storm recovery", "The President approved the major disaster declaration for 12 counties.")
        self.assertEqual((got["action"], got["from_title"]), ("approved", False))

    def test_if_approved_in_the_lead_is_not_an_approval(self):
        got = ds.classify("Statement on storm recovery",
                          "If approved, the declaration would bring federal aid. The governor requested a major disaster declaration.")
        self.assertEqual(got["action"], "request")

    def test_if_approved_in_the_headline_is_not_an_approval(self):
        got = ds.classify("Governor Requests Major Disaster Declaration; If Approved, Federal Aid Would Follow", "")
        self.assertEqual(got["action"], "request")

    def test_programs_are_read_from_the_lead(self):
        got = ds.classify("Governor requests major disaster declaration",
                          "asks for Public Assistance and Hazard Mitigation statewide")
        self.assertEqual(got["programs"], ["PA", "HM"])


class PageReadingTests(unittest.TestCase):
    def test_release_date_prefers_the_page(self):
        page = ds.parse_html(release("t", "body"))
        self.assertEqual(ds.release_date(page, "https://x.gov/a"), "2026-10-29")
        page = ds.parse_html('<meta property="article:published_time" content="2026-10-27T09:00:00-04:00">' + release("t", "b"))
        self.assertEqual(ds.release_date(page, "https://x.gov/a"), "2026-10-27")
        page = ds.parse_html("<main><p>Storm Recovery</p><p>OCTOBER 27, 2026</p><p>Albany, NY</p></main>")
        self.assertEqual(ds.release_date(page, "https://x.gov/a"), "2026-10-27")
        page = ds.parse_html("<main><p>No date here</p></main>")
        self.assertEqual(ds.release_date(page, "https://www.nj.gov/governor/news/2026/20261027a.shtml"), "2026-10-27")

    def test_the_lead_stops_before_related_news(self):
        page = ds.parse_html(release("Governor requests major disaster declaration", "Body text.",
                                     related="<h3>Related News</h3><p>Governor issues disaster proclamation</p>"))
        lead = ds.release_lead(page, "x")
        self.assertIn("Body text.", lead)
        self.assertNotIn("proclamation", lead)
        self.assertNotIn("Home News", lead)

    def test_html_listing_keeps_same_site_release_links(self):
        html = ('<a href="/news/gov-requests-major-disaster-declaration">Governor Requests Major Disaster Declaration Today</a>'
                '<a href="https://other.example.com/story">Governor Requests Major Disaster Declaration Elsewhere</a>'
                '<a href="/files/letter.pdf">Governor Requests Major Disaster Declaration Letter PDF</a>'
                '<a href="/about">About</a>'
                '<a href="/news/gov-requests-major-disaster-declaration#top">Governor Requests Major Disaster Declaration Today</a>')
        items = ds.parse_listing(html, "https://www.gov.example.gov/news", "html")
        self.assertEqual([i["url"] for i in items], ["https://www.gov.example.gov/news/gov-requests-major-disaster-declaration"])

    def test_rss_and_atom_listings(self):
        rss = ("<rss><channel><item><title>Governor Kelly requests a declaration of major presidential disaster</title>"
               "<link>https://www.kansastag.gov/CivicAlerts.aspx?aid=881</link>"
               "<pubDate>Thu, 29 Oct 2026 14:56:32 -0600</pubDate></item></channel></rss>")
        items = ds.parse_listing(rss, "https://www.kansastag.gov/RSSFeed.aspx", "rss")
        self.assertEqual((items[0]["url"], items[0]["feed_date"]), ("https://www.kansastag.gov/CivicAlerts.aspx?aid=881", "2026-10-29"))
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Major disaster request</title>'
                '<link href="https://gov.example.gov/a"/><updated>2026-10-30T10:00:00Z</updated></entry></feed>')
        self.assertEqual(ds.parse_listing(atom, "https://gov.example.gov/feed", "rss")[0]["url"], "https://gov.example.gov/a")
        self.assertEqual(ds.parse_listing("<rss><not closed", "https://x.gov", "rss"), [])


class FetcherTests(unittest.TestCase):
    def test_robots_disallow_is_obeyed_and_the_bot_names_itself(self):
        f, _ = fetcher({"https://gov.example.gov/robots.txt": "User-agent: *\nDisallow: /news/\n",
                        "https://gov.example.gov/news/": "secret"})
        with self.assertRaises(ds.Blocked):
            f.get("https://gov.example.gov/news/")
        self.assertNotIn("https://gov.example.gov/news/", [u for u, _ in f.session.calls])
        self.assertTrue(all(agent == UA for _, agent in f.session.calls))

    def test_robots_forbidden_means_nothing_is_fetched(self):
        f, _ = fetcher({"https://gov.example.gov/robots.txt": Resp("", 403), "https://gov.example.gov/a": "x"})
        with self.assertRaises(ds.Blocked):
            f.get("https://gov.example.gov/a")

    def test_missing_robots_allows(self):
        f, _ = fetcher({"https://gov.example.gov/a": "page"})
        self.assertEqual(f.get("https://gov.example.gov/a"), "page")

    def test_crawl_delay_is_honored_up_to_the_cap(self):
        f, clock = fetcher({"https://gov.example.gov/robots.txt": "User-agent: *\nCrawl-delay: 15\n",
                            "https://gov.example.gov/a": "a", "https://gov.example.gov/b": "b"})
        f.get("https://gov.example.gov/a")
        before = clock.now
        f.get("https://gov.example.gov/b")
        self.assertGreaterEqual(clock.now - before, 15)
        f2, clock2 = fetcher({"https://slow.example.gov/robots.txt": "User-agent: *\nCrawl-delay: 600\n",
                              "https://slow.example.gov/a": "a", "https://slow.example.gov/b": "b"})
        f2.get("https://slow.example.gov/a")
        before = clock2.now
        f2.get("https://slow.example.gov/b")
        self.assertLessEqual(clock2.now - before, ds.MAX_CRAWL_DELAY)

    def test_a_redirect_into_a_blocked_path_is_refused(self):
        f, _ = fetcher({"https://gov.example.gov/robots.txt": "User-agent: *\nDisallow: /private/\n",
                        "https://gov.example.gov/a": Resp("x", 200, "https://gov.example.gov/private/a")})
        with self.assertRaises(ds.Blocked):
            f.get("https://gov.example.gov/a")

    def test_http_errors_raise(self):
        f, _ = fetcher({"https://gov.example.gov/a": Resp("", 500)})
        with self.assertRaises(RuntimeError):
            f.get("https://gov.example.gov/a")


class MatchTests(unittest.TestCase):
    REQS = [req("ne-dr-2026-08-31-appeal", "NE", "DR", "2026-08-31", appeal=True),
            req("ne-dr-2026-10-26", "NE", "DR", "2026-10-26"),
            req("ks-dr-2026-09-15", "KS", "DR", "2026-09-15"),
            req("wa-dr-2026-09-25", "WA", "DR", "2026-09-25"),
            req("wa-em-2026-09-26", "WA", "EM", "2026-09-26"),
            req("fl-dr-2026-10-15", "FL", "DR", "2026-10-15", status="declared", decision="2026-10-27"),
            req("sd-dr-2026-09-29", "SD", "DR", "2026-09-29", tribe="Rosebud Sioux Tribe")]

    def test_request_release_matches_the_request_filed_just_before(self):
        self.assertEqual(ds.match(item("NE", "request", "DR", "2026-10-27"), self.REQS)[:2], ("ne-dr-2026-10-26", True))

    def test_an_appeal_release_picks_the_appeal(self):
        reqs = [req("id-dr-2026-10-20-appeal", "ID", "DR", "2026-10-20", appeal=True),
                req("id-dr-2026-10-22", "ID", "DR", "2026-10-22")]
        self.assertEqual(ds.match(item("ID", "request", "DR", "2026-10-23", appeal=True), reqs)[:2],
                         ("id-dr-2026-10-20-appeal", True))
        self.assertFalse(ds.match(item("ID", "request", "DR", "2026-10-23"), reqs)[1])

    def test_a_request_nobody_tracked_is_new(self):
        self.assertEqual(ds.match(item("KS", "request", "DR", "2026-10-29"), self.REQS)[:2], ("new", True))

    def test_new_is_not_certain_when_an_open_request_is_close(self):
        rid, strong, _ = ds.match(item("WA", "request", "DR", "2026-10-15"), self.REQS)
        self.assertEqual((rid, strong), ("wa-dr-2026-09-25", False))

    def test_unknown_type_is_never_certain(self):
        rid, strong, _ = ds.match(item("NE", "request", None, "2026-10-27"), self.REQS)
        self.assertFalse(strong)

    def test_headline_that_does_not_say_is_never_certain(self):
        self.assertFalse(ds.match(item("NE", "request", "DR", "2026-10-27", from_title=False), self.REQS)[1])

    def test_decisions_go_to_the_one_open_request_of_that_type(self):
        self.assertEqual(ds.match(item("WA", "denied", "DR", "2026-11-03"), self.REQS)[:2], ("wa-dr-2026-09-25", True))
        self.assertEqual(ds.match(item("WA", "approved", "EM", "2026-11-03"), self.REQS)[:2], ("wa-em-2026-09-26", True))

    def test_two_open_requests_need_review_unless_the_appeal_settles_it(self):
        rid, strong, _ = ds.match(item("NE", "denied", "DR", "2026-11-03"), self.REQS)
        self.assertFalse(strong)
        rid, strong, _ = ds.match(item("NE", "denied", "DR", "2026-11-03", appeal=True), self.REQS)
        self.assertEqual((rid, strong), ("ne-dr-2026-08-31-appeal", True))

    def test_approval_of_an_already_declared_request_matches_near_the_declaration(self):
        self.assertEqual(ds.match(item("FL", "approved", "DR", "2026-10-28"), self.REQS)[0], "fl-dr-2026-10-15")
        self.assertIsNone(ds.match(item("FL", "approved", "DR", "2026-12-20"), self.REQS)[0])

    def test_a_request_long_off_the_brief_is_not_closed_by_a_new_release(self):
        reqs = [req("ok-dr-2026-07-01", "OK", "DR", "2026-07-01", status="left_brief", last_seen="2026-08-20")]
        self.assertIsNone(ds.match(item("OK", "denied", "DR", "2026-11-03"), reqs)[0])
        reqs = [req("ok-dr-2026-10-01", "OK", "DR", "2026-10-01", status="left_brief", last_seen="2026-10-20")]
        self.assertEqual(ds.match(item("OK", "denied", "DR", "2026-11-03"), reqs)[0], "ok-dr-2026-10-01")

    def test_a_decision_cannot_come_before_the_request(self):
        self.assertIsNone(ds.match(item("NE", "approved", "DR", "2026-08-01"), self.REQS)[0])

    def test_state_releases_never_land_on_tribal_requests(self):
        self.assertIsNone(ds.match(item("SD", "approved", "DR", "2026-11-03"), self.REQS)[0])


def accepted_row(rid, action, published, state="NE", typ="DR", url=None):
    return {"url": url or f"https://gov.example.gov/{rid}-{action}", "request_id": rid, "action": action, "type": typ,
            "state": state, "requester": "", "publisher": "Office of the Governor", "title": "t",
            "published": published, "added": "2026-11-04", "added_by": "auto", "note": ""}


class AttachTests(unittest.TestCase):
    def test_sources_hang_on_their_request_in_date_order(self):
        reqs = [dict(req("ne-dr-2026-10-26", "NE", "DR", "2026-10-26"))]
        ds.attach(reqs, [accepted_row("ne-dr-2026-10-26", "denied", "2026-11-03"),
                         accepted_row("ne-dr-2026-10-26", "request", "2026-10-27")])
        self.assertEqual([s["action"] for s in reqs[0]["sources"]], ["request", "denied"])

    def test_a_release_settles_a_request_openfema_has_not(self):
        reqs = [dict(req("ne-dr-2026-10-26", "NE", "DR", "2026-10-26"))]
        ds.attach(reqs, [accepted_row("ne-dr-2026-10-26", "denied", "2026-11-03")])
        self.assertEqual((reqs[0]["status"], reqs[0]["decision_date"], reqs[0]["days"]), ("denied_per_source", "2026-11-03", 8))

    def test_openfema_outcome_wins_over_a_release(self):
        reqs = [dict(req("fl-dr-2026-10-15", "FL", "DR", "2026-10-15", status="declared", decision="2026-10-27"))]
        ds.attach(reqs, [accepted_row("fl-dr-2026-10-15", "approved", "2026-10-28", state="FL")])
        self.assertEqual(reqs[0]["status"], "declared")

    def test_new_requests_come_from_request_releases_only(self):
        rows = [accepted_row("new", "request", "2026-10-29", state="KS"),
                accepted_row("new", "approved", "2026-11-02", state="KS"),
                accepted_row("new", "request", "2026-10-29", state="KS", typ="")]
        made = ds.announced_requests(rows, {"KS": "Kansas"})
        self.assertEqual([(r["id"], r["requester"], r["source"]) for r in made],
                         [("ks-dr-2026-10-29-announced", "Kansas", "announced")])

    def test_rows_for_unknown_requests_are_reported(self):
        reqs = [dict(req("ne-dr-2026-10-26", "NE", "DR", "2026-10-26"))]
        orphans = ds.attach(reqs, [accepted_row("zz-dr-2026-01-01", "request", "2026-01-02")])
        self.assertEqual(len(orphans), 1)


class ReviewTests(unittest.TestCase):
    def test_decisions_move_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            acc, rev = Path(tmp) / "a.csv", Path(tmp) / "r.csv"
            ds.write_csv(acc, ds.ACCEPTED_FIELDS, [])
            rows = [{"decision": "accept", "url": "u1", "suggested_request_id": "ne-dr-2026-10-26", "action": "denied",
                     "reason": "two fit"},
                    {"decision": "reject", "url": "u2"}, {"decision": "", "url": "u3"}]
            ds.write_csv(rev, ds.REVIEW_FIELDS, rows)
            rejected = ds.apply_review_decisions(acc, rev, "2026-11-05")
            self.assertEqual(rejected, ["u2"])
            accepted = ds.read_csv(acc)
            self.assertEqual([(r["url"], r["request_id"], r["added_by"]) for r in accepted],
                             [("u1", "ne-dr-2026-10-26", "review")])
            self.assertEqual([r["url"] for r in ds.read_csv(rev)], ["u3"])


NEWSROOM = "https://governor.example.gov/news"


def newsroom_pages(*links, robots="User-agent: *\nAllow: /\n"):
    html = "".join(f'<a href="{href}">{title}</a>' for href, title, _ in links)
    pages = {NEWSROOM: html, "https://governor.example.gov/robots.txt": robots}
    for href, title, body in links:
        pages["https://governor.example.gov" + href] = body
    return pages


FEED = [{"code": "NE", "requester": "Nebraska", "publisher": "Office of the Governor", "kind": "html", "url": NEWSROOM}]


class CrawlTests(unittest.TestCase):
    def run_crawl(self, pages, requests, ignored=None, feeds=FEED, budget=10_000):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        acc, rev = Path(tmp.name) / "a.csv", Path(tmp.name) / "r.csv"
        f, _ = fetcher(pages, budget)
        health = ds.crawl(feeds, requests, f, acc, rev, ignored if ignored is not None else set(), "2026-11-04")
        return health, ds.read_csv(acc), ds.read_csv(rev), f

    def test_a_certain_match_is_filed_and_the_rest_reviewed(self):
        pages = newsroom_pages(
            ("/r1", "Gov. Pillen Requests Federal Disaster Declaration for Flood Damaged Counties",
             release("Gov. Pillen Requests Federal Disaster Declaration for Flood Damaged Counties",
                     "Governor Pillen has requested a federal disaster declaration for public assistance.",
                     date_line="October 27, 2026")),
            ("/r2", "Governor Advocates for Federal Disaster Aid for Farmers and Families",
             release("Governor Advocates for Federal Disaster Aid", "urged FEMA on the pending major disaster declaration")),
            ("/r3", "Governor Requests Physical Disaster Declaration from the SBA", "never opened"),
            ("/r4", "Governor Announces New Highway Funding Across the State", "never opened"))
        health, acc, rev, f = self.run_crawl(pages, [req("ne-dr-2026-10-26", "NE", "DR", "2026-10-26")])
        self.assertEqual([(r["request_id"], r["action"], r["published"], r["added_by"]) for r in acc],
                         [("ne-dr-2026-10-26", "request", "2026-10-27", "auto")])
        self.assertEqual([(r["action"], r["decision"]) for r in rev], [("unclear", "")])
        opened = [u for u, _ in f.session.calls]
        self.assertNotIn("https://governor.example.gov/r3", opened)
        self.assertNotIn("https://governor.example.gov/r4", opened)
        self.assertEqual((health[0]["status"], health[0]["added"], health[0]["queued"]), ("ok", 1, 1))

    def test_the_page_date_beats_a_feed_edit_date(self):
        feed_url = "https://governor.example.gov/feed"
        rss = ("<rss><channel><item><title>Governor Kelly requests a declaration of major presidential disaster</title>"
               "<link>https://governor.example.gov/r1</link><pubDate>Mon, 02 Nov 2026 10:00:00 -0600</pubDate>"
               "</item></channel></rss>")
        pages = {feed_url: rss, "https://governor.example.gov/robots.txt": "",
                 "https://governor.example.gov/r1": release("Governor Kelly requests a declaration of major presidential disaster",
                                                            "public assistance", date_line="FOR IMMEDIATE RELEASE: Oct. 29, 2026")}
        _, acc, _, _ = self.run_crawl(pages, [], feeds=[dict(FEED[0], code="KS", kind="rss", url=feed_url)])
        self.assertEqual((acc[0]["published"], acc[0]["request_id"]), ("2026-10-29", "new"))

    def test_known_and_ignored_releases_are_not_opened_again(self):
        pages = newsroom_pages(("/r1", "Governor Requests Major Disaster Declaration for Storms", "x"))
        ignored = {"https://governor.example.gov/r1"}
        _, acc, rev, f = self.run_crawl(pages, [], ignored=ignored)
        self.assertNotIn("https://governor.example.gov/r1", [u for u, _ in f.session.calls])
        self.assertEqual((acc, rev), ([], []))

    def test_releases_that_turn_out_not_federal_are_remembered(self):
        pages = newsroom_pages(("/r1", "Governor Signs Disaster Declaration for County Flooding",
                                release("Governor Signs Disaster Declaration", "a state disaster proclamation for two counties")))
        ignored = set()
        _, acc, rev, _ = self.run_crawl(pages, [], ignored=ignored)
        self.assertEqual((acc, rev), ([], []))
        self.assertIn("https://governor.example.gov/r1", ignored)

    def test_blocked_newsroom_is_reported_not_read(self):
        pages = newsroom_pages(("/r1", "Governor Requests Major Disaster Declaration for Storms", "x"),
                               robots="User-agent: *\nDisallow: /\n")
        health, _, _, f = self.run_crawl(pages, [])
        self.assertEqual(health[0]["status"], "blocked by robots.txt")
        self.assertEqual([u for u, _ in f.session.calls], ["https://governor.example.gov/robots.txt"])

    def test_skipped_unreadable_and_empty_sources_are_reported(self):
        feeds = [dict(FEED[0], kind="skip", note="bot protection"),
                 dict(FEED[0], url="https://broken.example.gov/news"),
                 dict(FEED[0], url="https://empty.example.gov/news")]
        pages = {"https://empty.example.gov/news": "<p>nothing</p>"}
        health, _, _, _ = self.run_crawl(pages, [], feeds=feeds)
        self.assertEqual(health[0]["status"], "skipped: bot protection")
        self.assertTrue(health[1]["status"].startswith("could not be read"))
        self.assertEqual(health[2]["status"], "no releases found on the page")

    def test_only_a_few_releases_per_newsroom_per_run(self):
        links = [(f"/r{i}", f"Governor Requests Major Disaster Declaration number {i}",
                  release("Governor Requests Major Disaster Declaration", "public assistance")) for i in range(9)]
        health, _, _, _ = self.run_crawl(newsroom_pages(*links), [])
        self.assertEqual(health[0]["opened"], ds.MAX_RELEASES_PER_SOURCE)

    def test_the_time_limit_stops_the_crawl(self):
        feeds = [FEED[0], dict(FEED[0], code="KS", url="https://other.example.gov/news")]
        health, _, _, _ = self.run_crawl(newsroom_pages(), [], feeds=feeds, budget=-1)
        self.assertTrue(all(h["status"].startswith("not reached") for h in health))

    def test_stored_titles_carry_no_long_dashes(self):
        title = "Governor Requests Major Disaster Declaration \u2013 Storm Recovery"
        pages = newsroom_pages(("/r1", title, release(title, "public assistance requested", date_line="October 27, 2026")))
        _, acc, rev, _ = self.run_crawl(pages, [req("ne-dr-2026-10-26", "NE", "DR", "2026-10-26")])
        stored = (acc + rev)[0]["title"]
        self.assertNotIn("\u2013", stored)
        self.assertIn(" - Storm Recovery", stored)


class TrackerIntegrationTests(unittest.TestCase):
    def test_build_crawls_then_shows_new_requests_and_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            old = (dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH)
            dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = out, out / "t.json", out / "c.json"
            feeds = ds.load_feeds
            ds.load_feeds = lambda path=None: [dict(FEED[0], code="KS", requester="Kansas")]
            pages = newsroom_pages(("/r1", "Governor Kelly requests a declaration of major presidential disaster",
                                    release("Governor Kelly requests a declaration of major presidential disaster",
                                            "a major presidential disaster declaration for Public Assistance")))
            f, _ = fetcher(pages)
            try:
                ledger = dt.build(today="2026-11-04", fema_override={}, scrape=True, fetcher=f)
                dt.write(ledger)
            finally:
                dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = old
                ds.load_feeds = feeds
            new = [r for r in ledger["requests"] if r.get("source") == "announced"]
            self.assertEqual([(r["id"], r["status"], r["days"]) for r in new], [("ks-dr-2026-10-29-announced", "open", 6)])
            self.assertEqual(new[0]["sources"][0]["action"], "request")
            self.assertEqual(ledger["sources_checked"][0]["status"], "ok")
            with (out / "declaration-sources.csv").open(newline="", encoding="utf-8") as fh:
                self.assertEqual(len(list(csv.DictReader(fh))), 1)

    def test_a_rejected_release_is_remembered_and_never_queued_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            ds.write_csv(out / "declaration-sources-review.csv", ds.REVIEW_FIELDS,
                         [{"decision": "reject", "url": "https://governor.example.gov/r1"}])
            old = (dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH)
            dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = out, out / "t.json", out / "c.json"
            try:
                ledger = dt.build(today="2026-11-04", fema_override={})
            finally:
                dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = old
            self.assertIn("https://governor.example.gov/r1", ledger["_cache"]["sources"]["ignored"])
            self.assertEqual(ds.read_csv(out / "declaration-sources-review.csv"), [])

    def test_tracker_without_scrape_never_touches_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            old = (dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH)
            dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = out, out / "t.json", out / "c.json"
            boom, tried = ds.Fetcher.__init__, []

            def refuse(self, *a, **k):
                tried.append(True)
                raise AssertionError("network used")
            ds.Fetcher.__init__ = refuse
            os.environ["DD_TRACKER_SCRAPE"] = "1"
            try:
                dt.build(today="2026-11-04", fema_override={})
            finally:
                os.environ["DD_TRACKER_SCRAPE"] = "0"
                ds.Fetcher.__init__ = boom
                dt.BRIEF_DIR, dt.LEDGER_PATH, dt.CACHE_PATH = old
            self.assertEqual(tried, [])


class AnnouncedResolveTests(unittest.TestCase):
    def test_announced_requests_resolve_beside_briefing_requests(self):
        day = "2026-10-29"
        row = {"brief": day, "code": "KS", "state": "KS", "tribe": None, "type": "DR", "incident": "Storms",
               "appeal": False, "status": None, "requested": "2026-09-15", "programs": None}
        briefs = {"2026-10-20.pdf": {"date": "2026-10-20", "has_table": True, "rows": [dict(row, brief="2026-10-20")]},
                  day + ".pdf": {"date": day, "has_table": True, "rows": [dict(row, state="NE", code="NE")]}}
        reqs, _ = dt.fold_requests(briefs)
        reqs += ds.announced_requests([accepted_row("new", "request", "2026-10-29", state="KS")], dt.STATE_NAMES)
        fema = {"declarations": [{"femaDeclarationString": "DR-4960-KS", "state": "KS", "declarationType": "DR",
                                  "declarationDate": "2026-11-03T00:00:00.000Z", "declarationTitle": "SEVERE STORMS",
                                  "tribalRequest": False}]}
        dt.resolve(reqs, fema, ["2026-10-20", day], "2026-11-04")
        got = {r["id"]: (r["status"], (r["declaration"] or {}).get("id")) for r in reqs}
        self.assertEqual(got["ks-dr-2026-10-29-announced"], ("declared", "DR-4960-KS"))
        self.assertEqual(got["ks-dr-2026-09-15"], ("left_brief", None))


class RepoFileTests(unittest.TestCase):
    def test_feed_list_is_well_formed(self):
        rows = ds.load_feeds()
        codes = [r["code"] for r in rows]
        self.assertEqual(len(codes), len(set(codes)))
        states = {c for c in dt.STATE_NAMES if c not in ("AS", "FM", "MH", "PW", "VI", "PR", "GU", "MP")}
        self.assertEqual(states - set(codes), set())
        for r in rows:
            self.assertIn(r["kind"], ("rss", "html", "skip"), r["code"])
            self.assertTrue(r["url"].startswith("https://"), r["code"])
            self.assertIn(r["code"], dt.STATE_NAMES, r["code"])

    def test_accepted_sources_are_well_formed(self):
        path = ROOT / "archive" / "ops-briefings" / "declaration-sources.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            self.assertEqual(reader.fieldnames, ds.ACCEPTED_FIELDS)
            rows = list(reader)
        self.assertEqual(len({r["url"] for r in rows}), len(rows))
        for r in rows:
            self.assertIn(r["action"], ds.ACTIONS)
            self.assertIn(r["type"], ("DR", "EM", ""))
            self.assertRegex(r["published"], r"^20\d\d-\d\d-\d\d$")
            self.assertIn(r["added_by"], ("auto", "review", "manual"))
            self.assertTrue(r["url"].startswith("https://"))

    def test_no_long_dashes(self):
        for path in (HERE / "declaration_sources.py", HERE / "declaration_source_feeds.csv",
                     ROOT / "archive" / "ops-briefings" / "declaration-sources.csv", Path(__file__)):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2013", text, path.name)
            self.assertNotIn("\u2014", text, path.name)


if __name__ == "__main__":
    unittest.main()
