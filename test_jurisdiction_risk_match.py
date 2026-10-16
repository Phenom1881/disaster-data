#!/usr/bin/env python3
"""
test_jurisdiction_risk_match.py

How gen-jurisdiction-pages.py finds a county or city page's CDC SVI and FEMA
NRI rows. The page's FIPS code comes from that match, and so does its Plus
section (state-declarations.json is keyed by FIPS), so a page that misses
loses all three.

Stdlib only.  Run:  python -m unittest test_jurisdiction_risk_match
"""
import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # gen-jurisdiction-pages.py imports dd_classify
_SPEC = importlib.util.spec_from_file_location("gen_jurisdiction_pages", os.path.join(HERE, "gen-jurisdiction-pages.py"))
gjp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gjp)


def row(name, state):
    return {"county": name, "state": state}


# The SVI writes the kind ("Rock Island County"); the NRI does not ("Rock Island").
SVI = {
    "35013": row("Doña Ana County", "NM"), "35011": row("De Baca County", "NM"),
    "17099": row("LaSalle County", "IL"), "17161": row("Rock Island County", "IL"),
    "48507": row("Zavala County", "TX"), "51036": row("Charles City County", "VA"),
    "51760": row("Richmond City", "VA"), "51159": row("Richmond County", "VA"),
    "24005": row("Baltimore County", "MD"), "24510": row("Baltimore City", "MD"),
    "32510": row("Carson City", "NV"), "12086": row("Miami-Dade County", "FL"),
    "02150": row("Kodiak Island Borough", "AK"),
}
NRI = {
    "35013": row("Doña Ana", "NM"), "72011": row("Añasco", "PR"),
    "17161": row("Rock Island", "IL"), "02150": row("Kodiak Island", "AK"),
    "51036": row("Charles City", "VA"), "51095": row("James City", "VA"),
    "51760": row("Richmond", "VA"), "51159": row("Richmond", "VA"),
    "24005": row("Baltimore", "MD"), "24510": row("Baltimore", "MD"),
    "48501": row("Yoakum", "TX"), "29510": row("St. Louis", "MO"), "29189": row("St. Louis", "MO"),
}


def fips_for(lookup, name, kind, state):
    key = gjp.jurisdiction_risk_key({"name": name, "kind": kind}, state)
    return (lookup.get(key) or {}).get("fips")


class RiskMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svi = gjp.build_risk_lookup(SVI)
        cls.nri = gjp.build_risk_lookup(NRI)

    def test_accented_names_match_femas_plain_spelling(self):
        self.assertEqual(fips_for(self.svi, "Dona Ana County", "county", "NM"), "35013")
        self.assertEqual(fips_for(self.nri, "Dona Ana County", "county", "NM"), "35013")
        self.assertEqual(fips_for(self.nri, "Anasco Municipio", "county", "PR"), "72011")

    def test_names_that_differ_only_in_spacing_match(self):
        self.assertEqual(fips_for(self.svi, "La Salle County", "county", "IL"), "17099")
        self.assertEqual(fips_for(self.svi, "DeBaca County", "county", "NM"), "35011")

    def test_a_name_ending_in_island_or_city_is_not_cut_short(self):
        # Stripping " Island" from the NRI's "Rock Island" left "Rock".
        self.assertEqual(fips_for(self.nri, "Rock Island County", "county", "IL"), "17161")
        self.assertEqual(fips_for(self.nri, "Kodiak Island Borough", "county", "AK"), "02150")
        self.assertEqual(fips_for(self.nri, "Charles City County", "county", "VA"), "51036")
        self.assertEqual(fips_for(self.nri, "James City County", "county", "VA"), "51095")
        self.assertEqual(fips_for(self.svi, "Charles City County", "county", "VA"), "51036")

    def test_texas_counties_numbered_past_500_are_counties(self):
        self.assertEqual(fips_for(self.svi, "Zavala County", "county", "TX"), "48507")
        self.assertEqual(fips_for(self.nri, "Yoakum County", "county", "TX"), "48501")

    def test_independent_cities_and_same_named_counties_stay_apart(self):
        for lookup in (self.svi, self.nri):
            self.assertEqual(fips_for(lookup, "Richmond (city)", "city", "VA"), "51760")
            self.assertEqual(fips_for(lookup, "Richmond County", "county", "VA"), "51159")
            self.assertEqual(fips_for(lookup, "Baltimore (city)", "city", "MD"), "24510")
            self.assertEqual(fips_for(lookup, "Baltimore County", "county", "MD"), "24005")
        self.assertEqual(fips_for(self.nri, "St. Louis (city)", "city", "MO"), "29510")
        self.assertEqual(fips_for(self.nri, "St. Louis County", "county", "MO"), "29189")
        self.assertEqual(fips_for(self.svi, "Carson City (city)", "city", "NV"), "32510")

    def test_a_renamed_county_gets_the_current_counties_rows(self):
        self.assertEqual(fips_for(self.svi, "Dade County", "county", "FL"), "12086")
        self.assertIsNone(fips_for(self.svi, "Monroe County", "county", "FL"))   # no row, no guess

    def test_a_full_name_beats_a_name_cut_down_to_match(self):
        lookup = gjp.build_risk_lookup({"17161": row("Rock Island", "IL"), "17999": row("Rock", "IL")})
        self.assertEqual(fips_for(lookup, "Rock County", "county", "IL"), "17999")
        self.assertEqual(fips_for(lookup, "Rock Island County", "county", "IL"), "17161")


class RealDataTests(unittest.TestCase):
    """Against the county-svi.js and county-nri.js the site is built from."""

    PAGES = [  # (state, page name, kind, FIPS), pages that found no SVI or NRI row before
        ("NM", "Dona Ana County", "county", "35013"), ("NM", "DeBaca County", "county", "35011"),
        ("TX", "Yoakum County", "county", "48501"), ("TX", "Young County", "county", "48503"),
        ("TX", "Zapata County", "county", "48505"), ("TX", "Zavala County", "county", "48507"),
        ("IL", "La Salle County", "county", "17099"), ("LA", "La Salle Parish", "county", "22059"),
        ("FL", "Dade County", "county", "12086"), ("GA", "Georgetown - Quitman County", "county", "13239"),
        ("AK", "Wade Hampton Census Area", "county", "02158"),
    ]
    NRI_ONLY = [  # the SVI has these already, or does not cover Puerto Rico
        ("IL", "Rock Island County", "county", "17161"), ("AK", "Kodiak Island Borough", "county", "02150"),
        ("VA", "Charles City County", "county", "51036"), ("VA", "James City County", "county", "51095"),
        ("PR", "Mayaguez Municipio", "county", "72097"), ("PR", "Las Marias Municipio", "county", "72083"),
    ]

    @classmethod
    def setUpClass(cls):
        cls.svi = gjp.build_risk_lookup(gjp.load_svi())
        cls.nri = gjp.build_risk_lookup(gjp.load_nri())
        if not cls.svi or not cls.nri:
            raise unittest.SkipTest("county-svi.js or county-nri.js is missing")

    def test_pages_that_used_to_miss_now_find_their_rows(self):
        for state, name, kind, fips in self.PAGES:
            self.assertEqual(fips_for(self.svi, name, kind, state), fips, (state, name, "SVI"))
            self.assertEqual(fips_for(self.nri, name, kind, state), fips, (state, name, "NRI"))
        for state, name, kind, fips in self.NRI_ONLY:
            self.assertEqual(fips_for(self.nri, name, kind, state), fips, (state, name, "NRI"))

    def test_every_state_page_finds_its_rows_except_the_known_gaps(self):
        with open(os.path.join(HERE, "locality-index.js"), encoding="utf-8") as handle:
            text = handle.read()
        entries = json.JSONDecoder().raw_decode(text, text.index("["))[0]
        # Connecticut's counties became planning regions in the Census data;
        # these Alaska areas were split; Bedford city merged into Bedford County.
        known = {("CT", n) for n in ("Fairfield County", "Hartford County", "Litchfield County", "Middlesex County",
                                     "New Haven County", "New London County", "Tolland County", "Windham County")}
        known |= {("AK", "Valdez-Cordova Census Area"), ("AK", "Prince of Wales-Outer Ketchikan Census Area"),
                  ("AK", "Wrangell-Petersburg Census Area"), ("VA", "Bedford (city)"), ("NV", "Stewart Community (city)")}
        states = set(gjp.STATE_FIPS) - {"AS", "GU", "MP", "PR", "VI", "FM", "MH", "PW"}
        missing = []
        for name, state, _, _, _, kind, *_ in entries:
            if kind in ("county", "city") and state in states and (state, name) not in known:
                if not fips_for(self.svi, name, kind, state) or not fips_for(self.nri, name, kind, state):
                    missing.append((state, name))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
