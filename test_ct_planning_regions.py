#!/usr/bin/env python3
"""
test_ct_planning_regions.py

Connecticut's county pages and the CDC SVI / FEMA NRI. Since 2022 both
datasets report Connecticut only by its nine planning regions (FIPS 09110 to
09190), while FEMA declarations still name its eight counties (09001 to
09015). gen-jurisdiction-pages.py shows a county page the rows of the regions
its towns are in, using ct-planning-regions.json (build_ct_planning_regions.py).

Stdlib only.  Run:  python -m unittest test_ct_planning_regions
"""
import csv
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # gen-jurisdiction-pages.py imports dd_classify
_SPEC = importlib.util.spec_from_file_location("gen_jurisdiction_pages", os.path.join(HERE, "gen-jurisdiction-pages.py"))
gjp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gjp)
gjp.SRC_ROOT = HERE   # read the data files beside this test, wherever it is run from

import build_ct_planning_regions as builder  # noqa: E402

REGIONS_FILE = os.path.join(HERE, "ct-planning-regions.json")


def page(name, kind="county", **extra):
    j = {"name": name, "kind": kind, "svi": {}, "nri": {}, "risk_fips": "", "risk_regions": []}
    j.update(extra)
    return j


class RegionFileTests(unittest.TestCase):
    """ct-planning-regions.json as committed."""

    @classmethod
    def setUpClass(cls):
        with open(REGIONS_FILE, encoding="utf-8") as fh:
            cls.counties = json.load(fh)["counties"]
        with open(os.path.join(HERE, "county-fips.json"), encoding="utf-8") as fh:
            cls.fips_names = json.load(fh)

    def test_the_eight_counties_are_the_ones_fema_names(self):
        self.assertEqual(sorted(self.counties), ["09001", "09003", "09005", "09007", "09009", "09011", "09013", "09015"])
        for fips, county in self.counties.items():
            self.assertEqual(county["name"], self.fips_names[fips]["n"] + " County")

    def test_every_town_is_in_one_county_and_one_region(self):
        towns = [(town, fips, region["fips"]) for fips, county in self.counties.items()
                 for region in county["regions"] for town in region["towns"]]
        self.assertEqual(len(towns), 169)
        self.assertEqual(len({town for town, _, _ in towns}), 169)
        for fips, county in self.counties.items():
            self.assertEqual(county["towns"], sum(len(r["towns"]) for r in county["regions"]))
            counts = [len(r["towns"]) for r in county["regions"]]
            self.assertEqual(counts, sorted(counts, reverse=True))

    def test_every_region_has_svi_and_nri_rows(self):
        svi, nri = gjp.load_svi(), gjp.load_nri()
        regions = {r["fips"] for county in self.counties.values() for r in county["regions"]}
        self.assertEqual(regions, {"09110", "09120", "09130", "09140", "09150", "09160", "09170", "09180", "09190"})
        for fips in regions:
            self.assertIn(fips, svi)
            self.assertIn(fips, nri)
        for fips in self.counties:
            self.assertNotIn(fips, svi)   # why the county pages need this at all
            self.assertNotIn(fips, nri)


class BuilderTests(unittest.TestCase):
    FIELDS = ["town_name", "town_fips_2020", "town_fips_2022", "county_name", "county_fips_2020",
              "ce_name_2022", "ce_fips_2022"]

    def write(self, rows):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
        self.addCleanup(os.unlink, handle.name)
        with handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return handle.name

    @staticmethod
    def block(town, code, county, county_fips, region, region_fips):
        return {"town_name": town, "town_fips_2020": county_fips + code, "town_fips_2022": region_fips + code,
                "county_name": county, "county_fips_2020": county_fips,
                "ce_name_2022": region, "ce_fips_2022": region_fips}

    def test_towns_are_grouped_by_county_then_region_most_towns_first(self):
        path = self.write([
            self.block("Bristol", "08490", "Hartford", "09003", "Naugatuck Valley Planning Region", "09140"),
            self.block("Avon", "02060", "Hartford", "09003", "Capitol Planning Region", "09110"),
            self.block("Avon", "02060", "Hartford", "09003", "Capitol Planning Region", "09110"),   # a second block
            self.block("Berlin", "04300", "Hartford", "09003", "Capitol Planning Region", "09110"),
        ])
        expected = (builder.EXPECTED_TOWNS, builder.EXPECTED_COUNTIES, builder.EXPECTED_REGIONS)
        builder.EXPECTED_TOWNS, builder.EXPECTED_COUNTIES, builder.EXPECTED_REGIONS = 3, 1, 2
        try:
            data = builder.build(builder.read_towns(path))
        finally:
            builder.EXPECTED_TOWNS, builder.EXPECTED_COUNTIES, builder.EXPECTED_REGIONS = expected
        county = data["counties"]["09003"]
        self.assertEqual((county["name"], county["towns"]), ("Hartford County", 3))
        self.assertEqual([(r["short_name"], r["towns"]) for r in county["regions"]],
                         [("Capitol", ["Avon", "Berlin"]), ("Naugatuck Valley", ["Bristol"])])

    def test_a_town_in_two_counties_is_an_error(self):
        path = self.write([
            self.block("Avon", "02060", "Hartford", "09003", "Capitol Planning Region", "09110"),
            self.block("Avon", "02060", "Tolland", "09013", "Capitol Planning Region", "09110"),
        ])
        with self.assertRaises(ValueError):
            builder.read_towns(path)

    def test_a_short_crosswalk_is_an_error(self):
        path = self.write([self.block("Avon", "02060", "Hartford", "09003", "Capitol Planning Region", "09110")])
        with self.assertRaises(ValueError):
            builder.build(builder.read_towns(path))


class CountyPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svi = gjp.build_risk_lookup(gjp.load_svi())
        cls.nri = gjp.build_risk_lookup(gjp.load_nri())
        cls.counties = gjp.load_ct_planning_regions()

    def attach(self, *pages):
        pages = list(pages)
        gjp.attach_ct_planning_regions(pages, self.svi, self.nri, self.counties)
        return pages

    def test_a_county_page_gets_its_fips_and_its_regions_rows(self):
        hartford, tribal = self.attach(page("Hartford County"), page("Mohegan Trust Lands", kind="tribal"))
        self.assertEqual(hartford["risk_fips"], "09003")   # also keys its state declarations
        self.assertEqual([r["short_name"] for r in hartford["risk_regions"]],
                         ["Capitol", "Northwest Hills", "Naugatuck Valley"])
        capitol = hartford["risk_regions"][0]
        self.assertEqual((capitol["svi"]["fips"], capitol["nri"]["fips"]), ("09110", "09110"))
        self.assertEqual((tribal["risk_fips"], tribal["risk_regions"]), ("", []))

    def test_a_page_with_its_own_rows_is_left_alone(self):
        own = {"fips": "09003", "overall": 0.5}
        (hartford,) = self.attach(page("Hartford County", svi=own, risk_fips="09003"))
        self.assertEqual(hartford["risk_regions"], [])

    def test_the_page_says_where_the_figures_come_from(self):
        (hartford,) = self.attach(page("Hartford County"))
        text = gjp.risk_context_html(hartford)
        for expected in ("County FIPS 09003", "neither has a row for Hartford County",
                         "Its 29 towns are in three planning regions",
                         "26 of 29: all but Bristol, Burlington and Hartland", "1 of 29: Bristol",
                         "<td>58.8</td>", "97.4, Relatively High", "$302.3M, Relatively High"):
            self.assertIn(expected, text)
        self.assertNotIn("Social Vulnerability Index</h3>", text)   # no county card

    def test_a_county_inside_one_region(self):
        (middlesex,) = self.attach(page("Middlesex County"))
        text = gjp.risk_context_html(middlesex)
        self.assertIn("Its 15 towns are all in one planning region", text)
        self.assertIn("<td>All 15</td>", text)

    def test_other_pages_are_unchanged(self):
        self.assertEqual(gjp.risk_context_html(page("Nowhere County")), "")
        text = gjp.risk_context_html(page("Somewhere County", svi={"overall": 0.5, "fips": "01001"}))
        self.assertIn("Social Vulnerability Index", text)
        self.assertNotIn("Reported by planning region", text)

    def test_town_wording(self):
        county = ["A", "B", "C", "D", "E", "F", "G"]
        self.assertEqual(gjp._region_towns_text(county, county, True), "All 7")
        self.assertEqual(gjp._region_towns_text(["A", "B", "C"], county, True), "3 of 7: all but the 4 listed below")
        self.assertEqual(gjp._region_towns_text(["A", "B", "C", "D", "E"], county, True), "5 of 7: all but F and G")
        self.assertEqual(gjp._region_towns_text(["F", "G"], county, False), "2 of 7: F and G")


if __name__ == "__main__":
    unittest.main()
