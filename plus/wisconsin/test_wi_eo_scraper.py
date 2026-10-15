import json, unittest
import requests
from wi_eo_scraper import parse_archive, scrape


class WisconsinScraperTests(unittest.TestCase):
    def fixture(self, rows):
        return "<script>var WPQ1ListData = { \"Row\" :\n"+json.dumps(rows)+"};</script>"

    def test_parses_embedded_sharepoint_rows(self):
        page=self.fixture([{"Title2":"Gov. Evers Executive Order #256: Declaring a State of Emergency in Response to Severe Weather","URL":"/Documents/EO/EO256.pdf","Date":"4/1/2025"}])
        row=parse_archive(page)[0]
        self.assertEqual(row.eo_number,"256"); self.assertEqual(row.date_signed,"2025-04-01"); self.assertEqual(row.action_type,"declaration")

    def test_enriches_image_only_order_five_without_override(self):
        page=self.fixture([{"Title2":"Executive Order 5, Relating to Declaring a State of Emergency","URL":"/eo5.pdf","Date":"1/28/2019"}])
        row=parse_archive(page)[0]
        self.assertIn("Severe Winter Weather",row.title); self.assertEqual(row.hazard,"winter")

    def test_state_office_closure_is_operational_companion(self):
        page=self.fixture([{"Title2":"Executive Order 7, Relating to Declaring a State of Emergency and Closing State Office Buildings","URL":"/eo7.pdf","Date":"1/29/2019"}])
        self.assertEqual(parse_archive(page)[0].action_type,"operational")

# GovDelivery bulletins feed, as the Governor's releases are published there.
FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Office of the Governor</title>
<item><title>Press Release: Gov. Evers Declares State of Emergency in Response to Severe Storms throughout Eastern Wisconsin</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/42281e5</link>
<description>&lt;p&gt;Gov. Tony Evers today signed Executive Order #310 declaring a State of Emergency after severe storms.&lt;/p&gt;</description>
<pubDate>Wed, 02 Sep 2026 02:30:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Declares Emergency as State Prepares for Winter Storm</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/40e50fb</link>
<description>Snow and ice expected.</description><pubDate>Sat, 14 Mar 2026 18:00:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Declares State of Emergency Following Late June Storms</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/3a59cac</link>
<description>Storm damage.</description><pubDate>Tue, 28 Jul 2026 15:00:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Signs Executive Order Declaring State of Emergency, Period of Economic Disruption Due to the Ongoing Federal Government Shutdown</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/3f98f0a</link>
<description>FoodShare.</description><pubDate>Fri, 31 Oct 2025 15:00:00 +0000</pubDate></item>
<item><title>Press Release: Gov. Evers Announces Grants</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/1</link>
<description>Grants.</description><pubDate>Thu, 01 Oct 2026 15:00:00 +0000</pubDate></item>
</channel></rss>"""

SAVED_JOIN = ("declaration_id,governor,eo_number,event_description,date_signed,archive_record_url\n"
              "WI-EO-286,Tony Evers,286,Gov. Evers Executive Order #286: Declaring a State of Emergency in Response to Severe Winter Weather,2026-03-14,https://evers.wi.gov/Documents/EO/EO286.pdf\n"
              "WI-EO-300,Tony Evers,300,Gov. Evers Executive Order #300: Declaring a State of Emergency in Response to Severe Weather,2026-07-28,https://evers.wi.gov/Documents/EO/EO300.pdf\n")


class WisconsinPressReleaseFallbackTests(unittest.TestCase):
    """evers.wi.gov does not answer GitHub's servers; releases fill the gap."""

    def test_only_releases_naming_their_order_are_recorded(self):
        # A record without the archive's id could never be reconciled with
        # it later, so releases without an order number go to review.
        from wi_eo_scraper import feed_releases
        review = []
        found = feed_releases(FEED, review)
        self.assertEqual([(r.date_signed, r.eo_number) for r in found], [("2026-09-01", "310")])   # Sep 2 02:30 GMT is Sep 1 in Wisconsin
        self.assertEqual(found[0].title, "Gov. Evers Declares State of Emergency in Response to Severe Storms throughout Eastern Wisconsin")
        self.assertEqual(len(review), 2)

    def test_the_announced_order_number_is_the_one_signed(self):
        from wi_eo_scraper import announced_order
        self.assertEqual(announced_order("Building on Executive Order #300, Gov. Evers today signed Executive Order #315 declaring a State of Emergency"), "315")
        self.assertEqual(announced_order("Executive Order #320, declaring a State of Emergency, takes effect"), "320")
        self.assertEqual(announced_order("See Executive Order #300 and Executive Order #301"), "")
        self.assertEqual(announced_order("Executive Order #330 declares a state of emergency"), "330")

    def test_amending_release_is_not_a_new_declaration(self):
        from wi_eo_scraper import feed_releases
        feed = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Press Release: Gov. Evers Declares State of Emergency for Additional Counties After Flooding</title>
<link>https://content.govdelivery.com/accounts/WIGOV/bulletins/9</link>
<description>Executive Order #312, which amends Executive Order #310 and the state of emergency, adds counties.</description>
<pubDate>Fri, 04 Sep 2026 15:00:00 +0000</pubDate></item></channel></rss>"""
        review = []
        self.assertEqual(feed_releases(feed, review), [])
        self.assertEqual(len(review), 1)

    def test_fallback_keeps_saved_records_and_adds_the_new_order(self):
        import csv, tempfile
        from pathlib import Path
        from wi_eo_scraper import feed_releases, write_release_outputs
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "j.csv").write_text(SAVED_JOIN, encoding="utf-8")
            (tmp / "a.csv").write_text("declaration_id,eo_number,title,date_signed,action_type,hazard_category,archive_record_url\n", encoding="utf-8")
            added = write_release_outputs(feed_releases(FEED), tmp / "a.csv", tmp / "r.csv", tmp / "j.csv")
            with (tmp / "j.csv").open(encoding="utf-8") as f:
                rows = {r["declaration_id"]: r for r in csv.DictReader(f)}
        self.assertEqual(added, 1)
        self.assertEqual(set(rows), {"WI-EO-286", "WI-EO-300", "WI-EO-310"})
        self.assertEqual(rows["WI-EO-286"]["archive_record_url"], "https://evers.wi.gov/Documents/EO/EO286.pdf")   # saved row kept
        self.assertEqual(rows["WI-EO-310"]["date_signed"], "2026-09-01")

    def test_release_filters(self):
        from wi_eo_scraper import is_weather_emergency_release as ok
        self.assertTrue(ok("Press Release: Gov. Evers Declares State of Emergency for Severe Winter Weather in Northern Wisconsin"))
        self.assertFalse(ok("Press Release: Gov. Evers Declares Energy Emergency"))
        self.assertFalse(ok("Press Release: Gov. Evers Extends State of Emergency for Flood-Damaged Counties"))
        self.assertFalse(ok("Press Release: Gov. Evers Orders Flags to Half-Staff"))
        self.assertFalse(ok("Press Release: Gov. Evers Signs Bill to Support Emergency Responders After Tornadoes"))


class _Resp:
    def __init__(self,text="",status=200): self.text=text; self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400: raise requests.HTTPError(f"{self.status_code}")


class _Session:
    def __init__(self,*steps): self.steps=list(steps); self.calls=0
    def get(self,url,**kw):
        self.calls+=1; step=self.steps.pop(0)
        if isinstance(step,Exception): raise step
        return step


class ArchiveRetryTests(unittest.TestCase):
    PAGE="<script>var WPQ1ListData = { \"Row\" :\n"+json.dumps([{"Title2":"Executive Order 5, Relating to Declaring a State of Emergency","URL":"/eo5.pdf","Date":"1/28/2019"}])+"};</script>"

    def test_second_try_succeeds_after_a_connect_timeout(self):
        s=_Session(requests.ConnectTimeout("t"),_Resp(self.PAGE)); log=[]
        rows=scrape(s,waits=(0,0,0),attempts_log=log)
        self.assertEqual(len(rows),1); self.assertEqual(s.calls,2); self.assertEqual(log,["try 1: ConnectTimeout"])

    def test_error_status_and_missing_table_are_retried(self):
        s=_Session(_Resp("",503),_Resp("<html></html>"),_Resp(self.PAGE))
        self.assertEqual(len(scrape(s,waits=(0,0,0))),1); self.assertEqual(s.calls,3)

    def test_gives_up_after_the_last_try_and_reports_each(self):
        s=_Session(*[requests.ConnectTimeout("t")]*3); log=[]
        with self.assertRaises(requests.RequestException): scrape(s,waits=(0,0,0),attempts_log=log)
        self.assertEqual(s.calls,3); self.assertEqual(len(log),3)


# ------------------------------------------------- Internet Archive copy
from datetime import datetime, timedelta, timezone
import wi_eo_scraper as wi

NOW=datetime(2026,10,15,12,0,tzinfo=timezone.utc)
# The archive page as the site serves it: the same SharePoint table, here
# with three orders. The Internet Archive's id_ copy is these exact bytes.
ARCHIVE_PAGE=("<html><script>var WPQ1ListData = { \"Row\" :\n"+json.dumps([
    {"ID":"336","Title2":"Gov. Evers Executive Order #300: Declaring a State of Emergency in Response to Severe Weather","URL":"/Documents/EO/EO300-EmergencyOrderSevereWeather.pdf","Date":"7/28/2026"},
    {"ID":"337","Title2":"Gov. Evers Executive Order #301: Relating to Declaring a State of Emergency in Response to Severe Weather","URL":"/Documents/EO/EO301-EmergencyOrderHoursofService.pdf","Date":"8/3/2026"},
    {"ID":"341","Title2":"Gov. Evers Executive Order #305: Relating to a Proclamation that the Flag Be Flown at Half-Staff","URL":"/Documents/EO/EO305.pdf","Date":"10/9/2026"},
])+",\"FirstRow\" : 1};</script></html>")


class _IAResp:
    def __init__(self,text="",status=200,headers=None,url=""):
        self.text=text; self.status_code=status; self.headers=headers or {}; self.url=url; self.encoding=None
    def raise_for_status(self):
        if self.status_code>=400: raise requests.HTTPError(f"{self.status_code}")


class _IANet:
    """Answers the three Internet Archive addresses the scraper uses: the
    copy index (cdx), the copies themselves (id_) and Save Page Now (save).
    Each is a list of answers given in turn; the last one repeats."""
    def __init__(self,cdx=(),copies=None,save=()):
        self.cdx=list(cdx); self.copies=copies or {}; self.save=list(save); self.calls=[]
    @staticmethod
    def _next(answers):
        answer=answers[0] if len(answers)==1 else answers.pop(0)
        if isinstance(answer,Exception): raise answer
        return answer
    def get(self,url,params=None,**kw):
        self.calls.append((url,params))
        if "/cdx/search/cdx" in url: return self._next(self.cdx)
        if "/save/" in url: return self._next(self.save)
        stamp=url.split("/web/",1)[1][:14]
        return self.copies.get(stamp) or _IAResp("Not found",404)


def _cdx(*lines): return _IAResp("".join(line+"\n" for line in lines))


class InternetArchiveCopyTests(unittest.TestCase):
    """A run evers.wi.gov does not answer reads a current Internet Archive
    copy of the same page; an older copy is never used."""

    def run_copy(self,net):
        self.slept=[]
        return wi.archive_from_copy(net,now=NOW,sleep=self.slept.append)

    def test_a_copy_from_the_last_day_is_used_without_asking_for_a_new_one(self):
        net=_IANet(cdx=[_cdx("20261015020304 301","20261014220000 200","20261015090000 200")],
                   copies={"20261015090000":_IAResp(ARCHIVE_PAGE)})
        rows,stamp=self.run_copy(net)
        self.assertEqual(stamp,"20261015090000")   # the newest copy the site served normally
        self.assertEqual([r.eo_number for r in rows],["300","301","305"])
        self.assertFalse(any("/save/" in url for url,_ in net.calls))
        url,params=net.calls[0]
        self.assertEqual(params["from"],"20261014120000")   # only copies made in the last 24 hours
        self.assertEqual(params["url"],"evers.wi.gov/pages/newsroom/executive-orders.aspx")
        self.assertIn("/web/20261015090000id_/https://evers.wi.gov/pages/newsroom/executive-orders.aspx",net.calls[1][0])

    def test_copy_reads_the_same_as_the_site(self):
        net=_IANet(cdx=[_cdx("20261015090000 200")],copies={"20261015090000":_IAResp(ARCHIVE_PAGE)})
        rows,_=self.run_copy(net)
        self.assertEqual(rows,wi.parse_archive(ARCHIVE_PAGE))
        self.assertEqual(rows[0].url,"https://evers.wi.gov/Documents/EO/EO300-EmergencyOrderSevereWeather.pdf")   # links point at the Governor's site, not the archive
        self.assertEqual((rows[0].date_signed,rows[0].action_type),("2026-07-28","declaration"))

    def test_without_a_recent_copy_one_is_asked_for_and_read(self):
        made="20261015120030"
        net=_IANet(cdx=[_cdx("20261015093000 302")],   # a redirect the archive recorded is not a copy
                   save=[_IAResp("<html>saved</html>",headers={"Content-Location":f"/web/{made}/{wi.ARCHIVE_URL}"})],
                   copies={made:_IAResp(ARCHIVE_PAGE)})
        rows,stamp=self.run_copy(net)
        self.assertEqual(stamp,made); self.assertEqual(len(rows),3)
        self.assertTrue(net.calls[1][0].endswith("/save/"+wi.ARCHIVE_URL))

    def test_the_new_copy_is_found_when_the_answer_does_not_name_it(self):
        made="20261015120100"
        net=_IANet(cdx=[_cdx(),_cdx(),_cdx(f"{made} 200")],save=[_IAResp("<html>Saving page</html>")],
                   copies={made:_IAResp(ARCHIVE_PAGE)})
        rows,stamp=self.run_copy(net)
        self.assertEqual(stamp,made); self.assertEqual(self.slept,list(wi.SAVE_CHECKS[:2]))
        self.assertEqual(net.calls[-2][1]["from"],"20261015115500")   # copies made since the request, with 5 minutes of slack

    def test_a_refusal_fails_and_says_why(self):
        net=_IANet(cdx=[_cdx()],save=[_IAResp("Too Many Requests",429)])
        with self.assertRaises(wi.CopyUnavailable) as caught: self.run_copy(net)
        self.assertIn("no copy in the last 24 hours",str(caught.exception))
        self.assertIn("Save Page Now answered 429",str(caught.exception))

    def test_a_copy_that_never_appears_fails(self):
        net=_IANet(cdx=[_cdx()],save=[_IAResp("<html>Saving page</html>")])
        with self.assertRaises(wi.CopyUnavailable) as caught: self.run_copy(net)
        self.assertIn("not found in time",str(caught.exception)); self.assertEqual(self.slept,list(wi.SAVE_CHECKS))

    def test_a_copy_without_the_order_table_is_not_used(self):
        # A block or error page the archive copied has no table; asking for a
        # new copy that is no better ends in a failure, not an empty list.
        made="20261015120030"
        net=_IANet(cdx=[_cdx("20261015090000 200")],copies={"20261015090000":_IAResp("<html>Access denied</html>"),made:_IAResp("<html>Access denied</html>")},
                   save=[_IAResp("",headers={"Content-Location":f"/web/{made}/{wi.ARCHIVE_URL}"})])
        with self.assertRaises(wi.CopyUnavailable) as caught: self.run_copy(net)
        self.assertIn("copy 20261015090000 not readable (ValueError)",str(caught.exception))
        self.assertIn(f"new copy {made} not readable (ValueError)",str(caught.exception))

    def test_an_older_copy_served_in_place_of_the_new_one_is_refused(self):
        # Asked for a time it has no copy of, the archive redirects to the
        # nearest copy. August's copy must not pass for today's.
        made="20261015120030"
        old=_IAResp(ARCHIVE_PAGE,url=f"https://web.archive.org/web/20260828060219id_/{wi.ARCHIVE_URL}")
        net=_IANet(cdx=[_cdx()],copies={made:old},save=[_IAResp("",headers={"Content-Location":f"/web/{made}/{wi.ARCHIVE_URL}"})])
        with self.assertRaises(wi.CopyUnavailable) as caught: self.run_copy(net)
        self.assertIn(f"new copy {made} not readable (ValueError)",str(caught.exception))
        with self.assertRaises(ValueError) as why: wi.ia_copy_rows(net,made,NOW-timedelta(hours=24))
        self.assertIn("served its copy from 2026-08-28 06:02 UTC instead",str(why.exception))
        # Redirected to a copy that is itself recent, the served time is the one reported.
        recent=_IAResp(ARCHIVE_PAGE,url=f"https://web.archive.org/web/20261015115959id_/{wi.ARCHIVE_URL}")
        rows,stamp=wi.ia_copy_rows(_IANet(copies={made:recent}),made,NOW-timedelta(hours=24))
        self.assertEqual((stamp,len(rows)),("20261015115959",3))

    def test_a_failed_lookup_still_asks_for_a_new_copy(self):
        made="20261015120030"
        net=_IANet(cdx=[requests.ConnectionError("down")],copies={made:_IAResp(ARCHIVE_PAGE)},
                   save=[_IAResp("",headers={"Link":f'<{wi.ARCHIVE_URL}>; rel="original", <https://web.archive.org/web/{made}/{wi.ARCHIVE_URL}>; rel="memento"; datetime="Thu, 15 Oct 2026 12:00:30 GMT"'})])
        self.assertEqual(self.run_copy(net)[1],made)

    def test_named_copy(self):
        stamp="20261015120030"
        self.assertEqual(wi.named_copy(_IAResp(headers={"Content-Location":f"/web/{stamp}/{wi.ARCHIVE_URL}"})),stamp)
        link=(f'<{wi.ARCHIVE_URL}>; rel="original", <https://web.archive.org/web/timemap/link/{wi.ARCHIVE_URL}>; rel="timemap"; type="application/link-format", '
              f'<https://web.archive.org/web/20260828060219/{wi.ARCHIVE_URL}>; rel="first memento"; datetime="Fri, 28 Aug 2026 06:02:19 GMT", '
              f'<https://web.archive.org/web/{stamp}/{wi.ARCHIVE_URL}>; rel="memento"; datetime="Thu, 15 Oct 2026 12:00:30 GMT"')
        self.assertEqual(wi.named_copy(_IAResp(headers={"Link":link})),stamp)   # the memento, not the first memento
        self.assertEqual(wi.named_copy(_IAResp(url=f"https://web.archive.org/web/{stamp}/{wi.ARCHIVE_URL}")),stamp)
        self.assertEqual(wi.named_copy(_IAResp(headers={"Link":f'<https://web.archive.org/web/{wi.ARCHIVE_URL}>; rel="timegate"'},url="https://web.archive.org/save/"+wi.ARCHIVE_URL)),"")


class MainFallbackOrderTests(unittest.TestCase):
    """The order of sources when the archive does not answer: a current
    Internet Archive copy, then the press releases, then a failure."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        self.tmp=Path(tempfile.mkdtemp())
        (self.tmp/"j.csv").write_text(SAVED_JOIN,encoding="utf-8")
        (self.tmp/"a.csv").write_text("declaration_id,eo_number,title,date_signed,action_type,hazard_category,archive_record_url\n",encoding="utf-8")
        self.argv=["wi_eo_scraper.py","--actions-out",str(self.tmp/"a.csv"),"--relationships-out",str(self.tmp/"r.csv"),"--join-out",str(self.tmp/"j.csv")]
        self.patches=[mock.patch.object(wi.sys,"argv",self.argv),
                      mock.patch.object(wi,"scrape",side_effect=requests.ConnectTimeout("Connection to evers.wi.gov timed out")),
                      mock.patch.object(wi,"network_note",return_value="evers.wi.gov resolved to 192.0.2.1")]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def run_main(self):
        import contextlib, io
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err): wi.main()
        return out.getvalue(),err.getvalue()

    def join_ids(self):
        import csv
        with (self.tmp/"j.csv").open(encoding="utf-8") as f: return [r["declaration_id"] for r in csv.DictReader(f)]

    def test_a_current_copy_is_written_like_a_direct_read(self):
        from unittest import mock
        with mock.patch.object(wi,"archive_from_copy",return_value=(wi.parse_archive(ARCHIVE_PAGE),"20261015090000")), \
             mock.patch.object(wi,"scrape_releases") as releases:
            out,err=self.run_main()
        self.assertIn("Wisconsin: 3 executive orders processed (read from the Internet Archive's copy made 2026-10-15 09:00 UTC; the Governor's site did not answer this run)",out)
        self.assertEqual(self.join_ids(),["WI-EO-300","WI-EO-301"])
        releases.assert_not_called()
        self.assertIn("evers.wi.gov resolved to 192.0.2.1",err)

    def test_without_a_copy_the_press_releases_are_read(self):
        from unittest import mock
        with mock.patch.object(wi,"archive_from_copy",side_effect=wi.CopyUnavailable("no copy in the last 24 hours; Save Page Now answered 429")), \
             mock.patch.object(wi,"scrape_releases",return_value=wi.feed_releases(FEED)):
            out,err=self.run_main()
        self.assertIn("(read from the Governor's press releases)",out)
        self.assertIn("No current Internet Archive copy: no copy in the last 24 hours",err)
        self.assertEqual(self.join_ids(),["WI-EO-286","WI-EO-300","WI-EO-310"])

    def test_when_every_source_fails_the_reason_names_each(self):
        from unittest import mock
        with mock.patch.object(wi,"archive_from_copy",side_effect=wi.CopyUnavailable("no copy in the last 24 hours; Save Page Now answered 429")), \
             mock.patch.object(wi,"scrape_releases",side_effect=requests.HTTPError("406 Client Error: Not Acceptable")):
            with self.assertRaises(SystemExit) as caught: self.run_main()
        reason=str(caught.exception.code)
        self.assertIn("ConnectTimeout",reason); self.assertIn("Save Page Now answered 429",reason); self.assertIn("406",reason)
        self.assertEqual(self.join_ids(),["WI-EO-286","WI-EO-300"])   # saved records untouched


class AdapterNoteTests(unittest.TestCase):
    def collect_with(self,stdout,returncode=0,stderr=""):
        import contextlib, io, subprocess, tempfile
        from unittest import mock
        import wisconsin
        done=subprocess.CompletedProcess([],returncode,stdout,stderr)
        with mock.patch.object(wisconsin.subprocess,"run",return_value=done), tempfile.TemporaryDirectory() as tmp, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return wisconsin.collect(workdir=tmp,scripts_dir=tmp)[1]

    def test_note_says_when_the_archive_came_from_a_copy(self):
        note=self.collect_with("Wisconsin: 303 executive orders processed (read from the Internet Archive's copy made 2026-10-15 09:00 UTC; the Governor's site did not answer this run)\n")
        self.assertTrue(note.endswith("; the Governor's site did not answer this run, so the archive was read from the Internet Archive's copy made 2026-10-15 09:00 UTC"))

    def test_note_for_a_direct_read_and_for_the_press_releases(self):
        self.assertEqual(self.collect_with("Wisconsin: 303 executive orders processed\n"),
                         "2019-present structured Governor archive; 2000-2018 not covered; early PDFs may require OCR")
        self.assertIn("new declarations read from the Governor's press releases",
                      self.collect_with("Wisconsin: archive not reachable; 1 weather emergency press releases read, 0 new declarations added (read from the Governor's press releases)\n"))

    def test_a_failure_carries_the_last_line_of_the_reason(self):
        with self.assertRaises(RuntimeError) as caught:
            self.collect_with("",returncode=1,stderr="Wisconsin archive not reachable\nWisconsin archive scrape failed after 3 tries: ConnectTimeout; no current Internet Archive copy (x); press releases not read either: HTTPError: 406\n")
        self.assertIn("no current Internet Archive copy (x)",str(caught.exception))


if __name__=="__main__": unittest.main()
