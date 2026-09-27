"""Tests for az_eo_scraper.py. Offline: listing and release pages are
fixtures shaped like azgovernor.gov's.

    cd plus/arizona && python -m unittest test_az_eo_scraper
"""
import csv
import tempfile
import unittest
from pathlib import Path

import az_eo_scraper as az
from eo_storm_join import compatible_event_types

BASE = "https://azgovernor.gov/office-arizona-governor/news/"


def row_html(path, title, date):
    return (f'<div class="views-row"><h2><a href="/office-arizona-governor/news/{path}">{title}</a></h2>'
            f'<div class="type">News Release</div><div class="date">{date}</div>'
            f'<a href="/office-arizona-governor/news/{path}">Learn More</a></div>')


def listing(*rows):
    return ('<html><body><nav><a href="/news-releases">News</a></nav><div class="view-content">'
            + "".join(row_html(*row) for row in rows) + '</div><ul class="pager"><li>'
            '<a href="/news-releases?type%5Bpanopoly_news_article%5D=panopoly_news_article&amp;page=1">next</a>'
            '</li></ul></body></html>')


def release(title, date, *paragraphs):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (f'<html><body><nav>Governor Katie Hobbs Declares State of Emergency for Somewhere Else</nav>'
            f'<main><article><h1>{title}</h1><div class="date">{date}</div>'
            f'<div class="field-name-body">{body}</div></article></main>'
            f'<aside>Related: Governor Hobbs Declares State of Emergency for Another County. October 1, 2024</aside>'
            f'</body></html>')


GILA = ("2025/09/governor-katie-hobbs-declares-state-emergency-gila-county",
        "Governor Katie Hobbs Declares State of Emergency for Gila County Flooding", "September 27, 2025")
SBA = ("2025/10/sba-approves-disaster-declaration-gila-county-after-request",
       "SBA Approves Disaster Declaration in Gila County After Request from Governor Katie Hobbs and "
       "Arizona Department of Emergency and Military Affairs", "October 10, 2025")
TRADE = ("2025/10/governor-katie-hobbs-lead-trade-delegation-mexico-city-arizona",
         "Governor Katie Hobbs to Lead Trade Delegation to Mexico City with Arizona-Mexico Commission",
         "October 19, 2025")
HEAT = ("2023/08/governor-katie-hobbs-declares-heat-state-emergency",
        "Governor Katie Hobbs Declares Heat State of Emergency", "August 11, 2023")
SWORN = ("2023/01/katie-hobbs-sworn-arizonas-24th-governor",
         "Katie Hobbs Sworn In As Arizona's 24th Governor", "January 2, 2023")
ELECT = ("2022/12/governor-elect-katie-hobbs-announces-public-safety-cabinet",
         "Governor-Elect Katie Hobbs Announces Public Safety Cabinet Members", "December 29, 2022")

RELEASES = {
    BASE + GILA[0]: release(GILA[1], GILA[2],
                            "Governor Katie Hobbs declared a State of Emergency for Gila County following "
                            "catastrophic flooding caused by severe monsoon storms. The declaration deploys state resources."),
    BASE + HEAT[0]: release(HEAT[1], HEAT[2],
                            "PHOENIX \u2013 After 30 consecutive days of excessive heat warnings in Coconino, Maricopa, "
                            "and Pinal counties, Governor Katie Hobbs has declared a State of Emergency to support local "
                            "heat relief efforts.",
                            "In addition to the declaration, Governor Hobbs has signed an executive order."),
}


class FakeSite:
    """Serves listing pages by number and release pages by address, and
    records every request."""

    def __init__(self, pages, releases=RELEASES):
        self.pages, self.releases, self.requested = pages, releases, []

    def get(self, url):
        self.requested.append(url)
        if url in self.releases:
            return self.releases[url]
        page = 0 if url == az.NEWS_URL else int(url.rsplit("page=", 1)[1])
        return self.pages[page] if page < len(self.pages) else listing()


class ExecutiveOrderTests(unittest.TestCase):
    def test_listing_and_number_normalization(self):
        html = ('<div><h4>Extreme Heat Planning and Preparedness</h4><h3>Executive Order: 16</h3>'
                '<span>August 11, 2023</span><a href="/office-arizona-governor/executive-order/16">Learn More</a></div>')
        rows = az.parse_listing(html)
        self.assertEqual(rows[0][:3], ("2023-16", "Extreme Heat Planning and Preparedness", "2023-08-11"))

    def test_heat_plan_not_declaration(self):
        action = az.Action("2023-16", "Extreme Heat Planning and Preparedness", "2023-08-11",
                           "https://example.gov/16", "directing agencies to prepare for extreme heat")
        self.assertEqual(az.classify(action), "administrative")

    def test_declaration_and_join_schema(self):
        action = az.Action("2023-99", "Declaring a State of Emergency Due to Wildfires", "2023-06-01",
                           "https://example.gov/99", "I hereby declare a state of emergency due to wildfires")
        with tempfile.TemporaryDirectory() as root:
            paths = [root + "/" + n for n in ("a.csv", "r.csv", "j.csv")]
            az.write_outputs([action], *paths)
            with open(paths[2], encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(tuple(rows[0]), az.JOIN_FIELDS)

    def test_no_overrides(self):
        self.assertEqual(az.HAZARD_OVERRIDES, {})


class NewsListingTests(unittest.TestCase):
    def test_items_titles_and_dates(self):
        items = az.parse_news_listing(listing(GILA, SBA, TRADE))
        self.assertEqual([(i["title"][:40], i["date"]) for i in items], [
            ("Governor Katie Hobbs Declares State of E", "2025-09-27"),
            ("SBA Approves Disaster Declaration in Gil", "2025-10-10"),
            ("Governor Katie Hobbs to Lead Trade Deleg", "2025-10-19")])
        self.assertEqual(items[0]["url"], BASE + GILA[0])
        self.assertEqual((items[0]["year"], items[0]["month"]), (2025, 9))

    def test_date_beside_the_heading_in_a_list(self):
        html = ('<ul><li><span>August 11, 2023</span><h3><a href="https://azgovernor.gov/office-arizona-governor/'
                'news/2023/08/heat">Heat</a></h3></li><li><span>April 13, 2023</span><h3><a href="/office-arizona-'
                'governor/news/2023/04/yavapai">Yavapai</a></h3></li></ul>')
        self.assertEqual([(i["title"], i["date"]) for i in az.parse_news_listing(html)],
                         [("Heat", "2023-08-11"), ("Yavapai", "2023-04-13")])

    def test_a_date_is_not_borrowed_from_a_neighbor(self):
        html = ('<div><a href="/office-arizona-governor/news/2025/09/a">A</a> September 1, 2025 '
                '<a href="/office-arizona-governor/news/2025/08/b">B</a> August 31, 2025</div>')
        self.assertEqual([i["date"] for i in az.parse_news_listing(html)], ["", ""])


class DeclarationTitleTests(unittest.TestCase):
    def test_state_declarations_are_recognized(self):
        for title, kind in (
            (GILA[1], "declaration"),
            (HEAT[1], "declaration"),
            ("Governor Katie Hobbs Declares State of Emergency Over Greer Fire", "declaration"),
            ("Governor Hobbs Issues Declaration of Emergency to Repair Damages After Flooding in Yavapai County", "declaration"),
            ("Governor Katie Hobbs Declares State of Emergency, Requests Federal Assistance", "declaration"),
            ("Governor Hobbs Expands State of Emergency to Include Mohave County", "amendment"),
            ("Governor Hobbs Extends Declaration of Emergency for Havasupai Flooding", "extension"),
        ):
            self.assertEqual(az.declaration_kind(title), kind, title)

    def test_federal_and_unrelated_releases_are_not(self):
        for title in (SBA[1], TRADE[1],
                      "Governor Hobbs Condemns FEMA Denial of Disaster Declaration for Gila & Mohave County Flooding",
                      "Governor Hobbs Issues Statement on FEMA Emergency Declaration",
                      "Governor Katie Hobbs Signs Executive Order on Extreme Heat Preparedness"):
            self.assertEqual(az.declaration_kind(title), "", title)


class NewsRowTests(unittest.TestCase):
    def item(self, row):
        return az.parse_news_listing(listing(row))[0]

    def test_title_without_a_hazard_gets_the_release_sentence(self):
        text, date = az.parse_news_detail(RELEASES[BASE + HEAT[0]])
        self.assertEqual(date, "2023-08-11")
        row = az.news_row(self.item(HEAT), "declaration", text, date)
        self.assertEqual(row["event_description"],
                         "Governor Katie Hobbs Declares Heat State of Emergency. From the release: After 30 "
                         "consecutive days of excessive heat warnings in Coconino, Maricopa, and Pinal counties, "
                         "Governor Katie Hobbs has declared a State of Emergency to support local heat relief efforts.")
        self.assertIn("Excessive Heat", compatible_event_types(row["event_description"]))
        self.assertEqual(row["weather_related"], "true")
        self.assertEqual(row["declaration_id"], "AZ-DECL-2023-08-governor-katie-hobbs-declares-heat-state-emergency")

    def test_title_with_a_hazard_is_kept_as_is(self):
        text, date = az.parse_news_detail(RELEASES[BASE + GILA[0]])
        row = az.news_row(self.item(GILA), "declaration", text, date)
        self.assertEqual(row["event_description"], GILA[1])
        self.assertEqual((row["date_signed"], row["eo_number"], row["source_scope"]),
                         ("2025-09-27", "", az.NEWS_SCOPE))

    def test_emergency_without_weather_is_not_weather(self):
        item = self.item(("2025/08/oxbow", "Governor Katie Hobbs Declares State of Emergency in Response to "
                          "Oxbow Bridge Collapse", "August 20, 2025"))
        text, date = az.parse_news_detail(release(item["title"], "August 20, 2025",
                                                  "Governor Katie Hobbs declared a State of Emergency after the "
                                                  "collapse of the Oxbow Bridge."))
        self.assertEqual(az.news_row(item, "declaration", text, date)["weather_related"], "false")

    def test_named_fire_is_weather_and_has_a_reviewed_override(self):
        url = BASE + "2025/05/governor-katie-hobbs-declares-state-emergency-over-greer-fire"
        item = {"url": url, "title": "Governor Katie Hobbs Declares State of Emergency Over Greer Fire",
                "date": "2025-05-14", "year": 2025, "month": 5, "slug": ""}
        row = az.news_row(item, "declaration", "", "")
        self.assertEqual(row["weather_related"], "true")
        with (Path(__file__).parent / "hazard_overrides.csv").open(newline="", encoding="utf-8") as handle:
            overrides = {r["declaration_id"]: r["hazard_category_override"] for r in csv.DictReader(handle)}
        self.assertEqual(overrides.get(row["declaration_id"]), "fire")

    def test_sentences_from_other_releases_on_the_page_are_ignored(self):
        text, _ = az.parse_news_detail(release("Governor Hobbs Declares State of Emergency", "May 1, 2025",
                                               "The county asked for help."))
        self.assertEqual(az.declaration_sentence(text), "")


class CollectNewsTests(unittest.TestCase):
    def test_first_run_reads_back_to_the_start_of_the_term(self):
        site = FakeSite([listing(TRADE, SBA, GILA), listing(HEAT), listing(SWORN, ELECT), listing(ELECT)])
        rows, report = az.collect_news([], get=site.get)
        self.assertEqual(sorted(r["declaration_id"] for r in rows), [
            "AZ-DECL-2023-08-governor-katie-hobbs-declares-heat-state-emergency",
            "AZ-DECL-2025-09-governor-katie-hobbs-declares-state-emergency-gila-county"])
        pages = [u for u in site.requested if "/news/" not in u]
        self.assertEqual(len(pages), 4)       # stops at the page with nothing from the term
        details = [u for u in site.requested if "/news/" in u]
        self.assertEqual(sorted(details), sorted([BASE + GILA[0], BASE + HEAT[0]]))
        self.assertIn("(full archive)", report)
        self.assertIn("2 new emergency declaration(s), 2 in all", report)

    def test_later_runs_read_the_newest_pages_and_keep_saved_declarations(self):
        saved = [{"declaration_id": "AZ-DECL-2023-08-governor-katie-hobbs-declares-heat-state-emergency",
                  "action_type": "declaration", "source_scope": az.NEWS_SCOPE, "event_description": "Heat",
                  "date_signed": "2023-08-11", "weather_related": "true"},
                 {"declaration_id": "AZ-DECL-2025-09-governor-katie-hobbs-declares-state-emergency-gila-county",
                  "action_type": "declaration", "source_scope": az.NEWS_SCOPE, "event_description": "Gila",
                  "date_signed": "2025-09-27", "weather_related": "true"}]
        older = [listing((f"2025/0{n % 9 + 1}/release-{n}", f"Release {n}", "June 1, 2025")) for n in range(12)]
        site = FakeSite([listing(TRADE, SBA, GILA)] + older)
        rows, report = az.collect_news(saved, get=site.get)
        self.assertEqual(len([u for u in site.requested if "/news/" not in u]), az.WEEKLY_NEWS_PAGES)
        self.assertEqual([u for u in site.requested if "/news/" in u], [])   # saved ones are not re-read
        self.assertEqual({r["event_description"] for r in rows}, {"Heat", "Gila"})
        self.assertIn("0 new emergency declaration(s), 2 in all", report)

    def test_reading_stops_when_a_page_shows_nothing_new(self):
        sidebar = ("2026/09/governor-katie-hobbs-launches-program", "Governor Katie Hobbs Launches Program",
                   "September 17, 2026")
        site = FakeSite([listing(sidebar, GILA), listing(sidebar, HEAT)] + [listing(sidebar)] * 20)
        az.collect_news([], get=site.get)
        self.assertEqual(len([u for u in site.requested if "/news/" not in u]), 3)

    def test_an_empty_first_page_fails_the_state(self):
        with self.assertRaises(RuntimeError):
            az.collect_news([], get=FakeSite([listing()]).get)


class OutputTests(unittest.TestCase):
    def test_join_has_dated_weather_declarations_only(self):
        news = [
            {"declaration_id": "AZ-DECL-a", "action_type": "declaration", "weather_related": "true",
             "date_signed": "2025-09-27", "event_description": "Flooding"},
            {"declaration_id": "AZ-DECL-b", "action_type": "declaration", "weather_related": "false",
             "date_signed": "2025-08-20", "event_description": "Bridge collapse"},
            {"declaration_id": "AZ-DECL-c", "action_type": "amendment", "weather_related": "true",
             "date_signed": "2025-10-01", "event_description": "Expands flooding emergency"},
            {"declaration_id": "AZ-DECL-d", "action_type": "declaration", "weather_related": "true",
             "date_signed": "", "event_description": "Undated flooding"},
        ]
        for row in news:
            row.update({"state": "AZ", "governor": az.GOVERNOR, "eo_number": "", "action_kind": "emergency_declaration",
                        "end_date": "", "source_scope": az.NEWS_SCOPE, "document_format": "html",
                        "detail_url": "u", "archive_record_url": "u"})
        order = az.Action("2025-11", "Rescinding Outdated Executive Orders", "2025-06-01", "https://example.gov/11", "")
        with tempfile.TemporaryDirectory() as root:
            paths = [root + "/" + n for n in ("a.csv", "r.csv", "j.csv")]
            az.write_outputs([order], *paths, news_rows=news)
            with open(paths[2], encoding="utf-8") as handle:
                self.assertEqual([r["declaration_id"] for r in csv.DictReader(handle)], ["AZ-DECL-a"])
            with open(paths[0], encoding="utf-8") as handle:
                self.assertEqual([r["declaration_id"] for r in csv.DictReader(handle)],
                                 ["AZ-DECL-c", "AZ-DECL-a", "AZ-DECL-b", "AZ-2025-11", "AZ-DECL-d"])
            self.assertEqual(az.load_saved_news(paths[0])[0]["declaration_id"], "AZ-DECL-c")
            self.assertEqual(len(az.load_saved_news(paths[0])), 4)


if __name__ == "__main__":
    unittest.main()
