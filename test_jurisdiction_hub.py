#!/usr/bin/env python3
"""
test_jurisdiction_hub.py

A state's jurisdiction hub ranks its localities by major disaster
declarations, then by all declarations, the way each locality's own page
leads with major disasters. Stubs (tribal nations whose full page is in
another state) are counted the same way, from complete fiscal years.

Stdlib only.  Run:  python -m unittest test_jurisdiction_hub
"""
import importlib.util
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # gen-jurisdiction-pages.py imports dd_classify
_SPEC = importlib.util.spec_from_file_location("gen_jurisdiction_pages", os.path.join(HERE, "gen-jurisdiction-pages.py"))
gjp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gjp)


def page(name, dr, decl):
    return {"name": name, "label": "County", "slug": name.lower().replace(" ", "-"), "dr": dr, "decl": decl,
            "kind": "county", "noun": "County"}


def ranked(html):
    """(name, count text) for each row of the hub's ranking, in order."""
    rows = re.findall(r'<li><a href="[^"]+">([^<]+)</a> <span class="k">[^<]*</span>'
                      r'<span class="c">(.*?)</span></li>', html)
    return [(name, re.sub(r"<[^>]+>|&middot;", "", count).strip()) for name, count in rows]


class HubRankTests(unittest.TestCase):
    def test_major_disasters_rank_first_then_all_declarations_then_name(self):
        js = [page("Alpha County", 2, 20), page("Bravo County", 5, 6), page("Charlie County", 5, 9),
              page("Delta County", 5, 9), page("Echo County", 1, 3)]
        rows = ranked(gjp.render_hub(js, lcfy=2026))
        self.assertEqual([name for name, _ in rows],
                         ["Charlie County", "Delta County", "Bravo County", "Alpha County", "Echo County"])
        self.assertEqual(rows[0][1], "5 major disasters, 9 in all")
        self.assertEqual(rows[-1][1], "1 major disaster, 3 in all")

    def test_the_lede_says_how_the_hub_is_ranked(self):
        html = gjp.render_hub([page("Alpha County", 1, 1)], lcfy=2026)
        self.assertIn("ranked by federal major disaster declarations since FY2000, then by all "
                      "federal declarations", html)

    def test_a_stub_is_counted_from_complete_fiscal_years(self):
        by_id = {
            "DR-1-UT": {"declarationType": "DR", "fyDeclared": 2020},
            "EM-2-UT": {"declarationType": "EM", "fyDeclared": 2021},
            "DR-3-UT": {"declarationType": "DR", "fyDeclared": 2027},   # fiscal year still open
        }
        counts = gjp._stub_counts(["DR-1-UT", "EM-2-UT", "DR-3-UT", "DR-9-UT"], by_id, 2026)
        self.assertEqual(counts, {"decl": 2, "dr": 1})

    def test_a_stub_ranks_beside_the_pages(self):
        stub = {"name": "Navajo Nation Reservation", "label": "Tribal nation",
                "canonical_url": "states/arizona/navajo-nation-reservation-az.html",
                "primary_name": "Arizona", "decl": 19, "dr": 15}
        rows = ranked(gjp.render_hub([page("Alpha County", 4, 12)], stubs=[stub], lcfy=2026))
        self.assertEqual(rows[0], ("Navajo Nation Reservation",
                                   "15 major disasters, 19 in all  full record on the Arizona page"))


if __name__ == "__main__":
    unittest.main()
