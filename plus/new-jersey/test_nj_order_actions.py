"""What a New Jersey order does, read from its own operative text.

The excerpts are from the orders themselves on nj.gov (read 2026-10-16),
shortened. Run:  python -m unittest test_nj_order_actions
"""
import csv
import tempfile
import unittest
from pathlib import Path

import nj_eo_scraper as nj


def order(number, description="", text="", governor="Murphy", date="2025-12-30"):
    return nj.NJOrder(governor=governor, order_number=number, description=description, date_issued=date,
                      document_url=f"https://www.nj.gov/x/EO-{number}.pdf", document_format="pdf",
                      document_text=text)


EO_409 = (  # Murphy (Acting Governor Way), declares
    "EXECUTIVE ORDER NO. 409 WHEREAS, beginning in the afternoon on Friday, December 26, 2025, and continuing "
    "into Saturday, December 27, 2025, the State of New Jersey is forecasted to experience a severe winter storm "
    "causing hazardous weather conditions including heavy snow, sleet, and freezing rain; NOW, THEREFORE, I, "
    "TAHESHA L. WAY, Acting Governor of the State of New Jersey, in order to protect the health, safety, and welfare "
    "of the people of the State of New Jersey DO DECLARE and PROCLAIM that a State of Emergency exists throughout "
    "the State of New Jersey, effective at 1:00 p.m. on Friday, December 26, 2025; and I hereby ORDER and DIRECT the "
    "following: 1. I authorize and empower the State Director of Emergency Management ...")
EO_410 = (  # ends EO 409
    "EXECUTIVE ORDER NO. 410 WHEREAS, Executive Order No. 409, declaring a State of Emergency across all twenty-one "
    "(21) counties in New Jersey, was issued on Friday, December 26, 2025, due to the expected impacts of a winter "
    "storm, including snowfall, freezing rain, and sleet; NOW, THEREFORE, I, TAHESHA L. WAY, Acting Governor of the "
    "State of New Jersey, by virtue of the authority vested in me by the Constitution and the Statutes of this State, "
    "hereby ORDER and DIRECT: 1. The State of Emergency declared pursuant to Executive Order No. 409 (2025) is "
    "terminated effective 3:00 p.m., Eastern Standard Time, on Tuesday, December 30, 2025. GIVEN, under my hand and "
    "seal this 30 th day of December, Two Thousand and Twenty-Five")
EO_415 = (  # ends emergencies from three administrations
    "EXECUTIVE ORDER NO. 415 WHEREAS, Executive Order No. 73, declaring a State of Emergency across all twenty-one "
    "(21) counties in New Jersey, was issued on August 25, 2011, due to Hurricane Irene; NOW, THEREFORE, I, PHILIP D. "
    "MURPHY, Governor of the State of New Jersey, by virtue of the authority vested in me by the Constitution and by "
    "the Statutes of this State, do hereby ORDER and DIRECT: 1. The States of Emergency declared pursuant to the "
    "following executive orders are terminated effective at 5:00 p.m., Eastern Standard Time, on January 16, 2026: "
    "a. Executive Order No. 73 (2011) b. Executive Order No. 104 (2012) c. Executive Order No. 259 (2021) "
    "2. The State of Emergency declared pursuant to Executive Order No. 103 (2020) is terminated effective at 5:00 "
    "p.m., Eastern Standard Time, on January 16, 2026. GIVEN, under my hand and seal")
EO_114 = (  # Christie, rescinds the odd-even gas rationing order
    "EXECUTIVE ORDER NO. 114 WHEREAS, beginning on October 28, 2012, and continuing through October 30, 2012, "
    "Hurricane Sandy struck the State of New Jersey; NOW, THEREFORE, I, CHRIS CHRISTIE, Governor of the State of New "
    "Jersey, by virtue of the authority vested in me by the Constitution and by the Statutes of this State, do hereby "
    "ORDER and DIRECT: 1. Executive Order 108, signed on November 2, 2012 is rescinded. 2. This Order shall take "
    "effect at 6:00 a.m. on Tuesday, November 13, 2012.")
EO_109 = (  # Christie, administrative order after Sandy
    "EXECUTIVE ORDER NO. 109 WHEREAS, beginning on October 28, 2012, and continuing through October 30, 2012, "
    "Hurricane Sandy struck the State of New Jersey; NOW, THEREFORE, I, CHRIS CHRISTIE, Governor of the State of New "
    "Jersey, by virtue of the authority vested in me by the Constitution and by the statutes of this State, do hereby "
    "ORDER and DIRECT: 1. The restrictions on certain Sunday sales pursuant to N.J.S.A. 40A:64, et seq., are "
    "suspended. 2. This Order shall take effect immediately.")
EO_57 = (  # Christie storm order: no "declare" in its operative part
    "EXECUTIVE ORDER NO. 57 WHEREAS, the National Weather Service has issued a Flood Watch for the State of New "
    "Jersey predicting severe weather conditions, including heavy rains, high winds, main stream and river flooding; "
    "NOW, THEREFORE, I, CHRIS CHRISTIE, Governor of the State of New Jersey, by virtue of the authority vested in me "
    "by the Constitution and by the Statutes of this State, do hereby ORDER and DIRECT: 1. I authorize and empower "
    "the State Director of Emergency Management to activate those elements of the State Emergency Operations Plan")
WHITMAN_45_PAGE = (
    "State of New Jersey Executive Order #45 Governor Christine Todd Whitman Return to EO Index This executive order "
    "terminated by EO #46 Whitman. WHEREAS, severe weather conditions of January 7, 1996 caused by snow and blizzard "
    "conditions, including ...")
WHITMAN_45 = WHITMAN_45_PAGE + (  # the January 1996 blizzard: grants the emergency powers, never says "declare"
    " NOW THEREFORE, in accordance with the Laws of 1963 Chapter 109 (N.J.S.A. 38A:2-4), I hereby authorize the "
    "Adjutant General of the New Jersey National Guard to order to active duty such members of the New Jersey National "
    "Guard that, in his judgement, are necessary to provide aid to those localities where there is a threat or danger "
    "to the public health, safety, and welfare. ... FURTHERMORE, in accordance with the Laws of 1942, Chapter 251 as "
    "supplemented and amended, I hereby empower the Superintendent of the Division of State Police, who is the State's "
    "Director of Emergency ... GIVEN, under my hand and seal this 7th day of January ...")
FLORIO_85 = (  # the March 1993 blizzard
    "State of New Jersey Executive Order #85 Governor James J. Florio Return to EO Index This executive order has been "
    "rescinded by Order No. 86 (Florio). WHEREAS, severe weather conditions of March 13, 1993, including snow, heavy "
    "rains, winds and high tides have created ... THEREFORE, I, JAMES J. FLORIO, Governor of the State of New "
    "Jersey, in order to protect the health, safety and welfare of the people of the State of New Jersey do declare and "
    "proclaim that a limited State of Emergency has and presently exists throughout the State ... I hereby authorize "
    "the Adjutant General of the New Jersey National Guard to order to active duty such members ... I hereby empower the "
    "Superintendent of the Division of State Police, who is the State's Director of Emergency Management, ... GIVEN, "
    "under my hand and seal this 15th day of March ...")
WHITMAN_46 = (
    "State of New Jersey Executive Order #46 Governor Christine Todd Whitman Return to EO Index WHEREAS, Executive "
    "Order No. 45, declaring a state of emergency, was issued on January 8, 1996 because of severe weather "
    "conditions; and WHEREAS, the severity of the weather conditions necessitating the declaration of a state of "
    "emergency has eased; THEREFORE, I, Christine Todd Whitman, Governor of the State of New Jersey, announce that "
    "the state of emergency is hereby terminated effective at noon on January 13, 1996.")
WHITMAN_102 = (  # "DECLARE, ORDER and DIRECT" only opens the order; it ends EO 98's emergency
    "State of New Jersey Executive Order #102 Governor Christine Todd Whitman Return to EO Index This executive order "
    "terminates EO #98 Whitman. WHEREAS, Executive Order No. 98 was issued on August 5, 1999, for the purpose of "
    "declaring a state of water emergency due to drought conditions throughout New Jersey; and WHEREAS, Executive "
    "Order No. 100 was issued on September 14, 1999, in order to modify the areas designated under the water "
    "emergency due to drought conditions, by removing eight southern New Jersey counties; NOW, THEREFORE, I, "
    "Christine Todd Whitman, Governor of the State of New Jersey, by virtue of the authority vested in me by the "
    "Constitution and by the Statutes of this State, do hereby DECLARE, ORDER and DIRECT, as follows: 1. A state of "
    "water emergency, as declared by Executive Order No. 98, due to the drought no longer exists anywhere within the "
    "State and is hereby terminated in those counties as to which it was not previously terminated by Executive "
    "Order No. 100, issued September 14, 1999. 2. All persons are urged to use water wisely and to comply fully with "
    "water use measures ... 3. This Order shall take effect immediately. GIVEN, under my hand and seal this 27th day "
    "of September")
FLORIO_23 = (  # ratifies a verbal declaration and ends it in the same order
    "State of New Jersey Executive Order #23 Governor James J. Florio Return to EO Index WHEREAS, the storm which "
    "occurred on December 27 to December 28, 1990 created severe weather conditions; THEREFORE, I, JAMES J. FLORIO, "
    "Governor of the State of New Jersey, ORDER and DIRECT: (1) The verbal declaration by Acting Governor John A. "
    "Lynch of a Limited State of Emergency on December 28, 1990, is hereby ratified, and (2) ... the State of "
    "Emergency is hereby terminated effective 12:00 midnight on December 28, 1990.")
WHITMAN_61 = (
    "State of New Jersey Executive Order #61 Governor Christine Todd Whitman Return to EO Index WHEREAS, torrential "
    "rains and severe weather conditions occurred; NOW, THEREFORE, I, CHRISTINE TODD WHITMAN, Governor of the State "
    "of New Jersey, do memorialize the declaration and proclamation that a State of Emergency existed from October "
    "18, 1996 through October 21, 1996")
EO_233 = (  # Christie, aid to Puerto Rico
    "EXECUTIVE ORDER NO. 233 WHEREAS, on September 21, 2017, the President of the United States issued a Major "
    "Disaster Declaration for the Commonwealth of Puerto Rico due to the impact of Hurricane Maria; NOW, THEREFORE, "
    "I, CHRIS CHRISTIE, Governor of the State of New Jersey, in order to protect the health, safety, and welfare of "
    "the people of the State of New Jersey, do DECLARE AND PROCLAIM that a State of Emergency presently exists for "
    "the specific purpose of activating the Emergency Management Assistance Compact to coordinate multi-state "
    "mutual aid to the Commonwealth of Puerto Rico")
EO_315 = (  # clean energy policy that mentions storms
    "EXECUTIVE ORDER NO. 315 WHEREAS, global atmospheric warming is leading to more frequent and intense storms and "
    "flooding; NOW, THEREFORE, I, PHILIP D. MURPHY, Governor of the State of New Jersey, by virtue of the authority "
    "vested in me by the Constitution and by the Statutes of this State, do hereby ORDER and DIRECT: 1. It is the "
    "policy of the State to advance clean energy market mechanisms")


class OperativeTextTests(unittest.TestCase):
    def test_what_each_order_does(self):
        for name, text, expected in (
            ("EO 409", EO_409, "declaration"),
            ("EO 410", EO_410, "termination"),
            ("EO 415", EO_415, "termination"),
            ("EO 114", EO_114, "termination"),
            ("EO 109", EO_109, "administrative"),
            ("EO 57", EO_57, "declaration"),
            ("Whitman EO 45", WHITMAN_45, "declaration"),
            ("Whitman EO 46", WHITMAN_46, "termination"),
            ("Florio EO 85", FLORIO_85, "declaration"),
            ("Whitman EO 102", WHITMAN_102, "termination"),
            ("Florio EO 23", FLORIO_23, "declaration"),
            ("Whitman EO 61", WHITMAN_61, "declaration"),
            ("EO 315", EO_315, "administrative"),
        ):
            with self.subTest(name):
                self.assertEqual(nj.action_from_operative_text(text), expected)
        self.assertIsNone(nj.action_from_operative_text("WHEREAS, a storm; GIVEN under my hand"))

    def test_the_recitals_are_not_read(self):
        # Constructed from EO 410: a recital quoting the declaration it ends.
        quoted = EO_410.replace("NOW, THEREFORE", "WHEREAS, Executive Order No. 409 provided that a State of Emergency "
                                                  "exists throughout the State of New Jersey; NOW, THEREFORE")
        self.assertEqual(nj.action_from_operative_text(quoted), "termination")
        self.assertEqual(nj.ended_orders(quoted), [("409", "2025")])

    def test_an_order_with_no_description_is_classified_by_what_it_does(self):
        self.assertEqual(nj.classify_action_type(order("410", text=EO_410)), "termination")
        self.assertEqual(nj.classify_action_type(order("109", text=EO_109, governor="Christie")), "administrative")
        self.assertEqual(nj.classify_action_type(order("409", text=EO_409)), "declaration")
        self.assertEqual(nj.classify_action_type(order("102", text=WHITMAN_102, governor="Whitman")), "termination")
        self.assertEqual(nj.classify_action_type(order("1", text="")), "declaration")   # nothing to read: as before

    def test_the_archive_description_still_decides_when_it_can(self):
        self.assertEqual(nj.classify_action_type(order("322", "Governor Murphy Lifts Storm-Related State of Emergency")),
                         "termination")
        self.assertEqual(nj.classify_action_type(order("57", "Declares a Weather Related State of Emergency [pdf 22kB]",
                                                       text=EO_109)), "declaration")
        self.assertEqual(nj.classify_action_type(order(
            "102", "A state of water emergency, as declared by Executive Order No. 98, due to the drought no longer "
                   "exists anywhere within the State.", governor="Whitman")), "termination")
        self.assertEqual(nj.classify_action_type(order(
            "233", "Executive Order No. 233 to designate municipal and county law enforcement and emergency responders "
                   "as State Emergency Forces, which will be under the control and direction of the State Director of "
                   "Emergency Management.", text=EO_233, governor="Christie")), "declaration")


class ArchiveBannerTests(unittest.TestCase):
    def test_a_note_about_a_later_order_is_not_the_orders_title(self):
        # Whitman EO 45 and Florio EO 85, two blizzard declarations, read as terminations.
        self.assertIsNone(nj.recover_title_from_document(WHITMAN_45_PAGE + " " + "x" * 300))
        for number, governor, banner, text in (
            ("45", "Whitman", "Governor Christine Todd Whitman Return to EO Index This executive order terminated by "
                              "EO #46 Whitman", WHITMAN_45),
            ("85", "Florio", "Governor James J. Florio Return to EO Index This executive order has been rescinded by "
                             "Order No. 86 (Florio)", FLORIO_85),
        ):
            with self.subTest(governor):
                self.assertEqual(nj.clean_archive_text(banner), "")
                self.assertEqual(nj.classify_action_type(order(number, banner, text=text, governor=governor)),
                                 "declaration")
                self.assertTrue(nj.is_weather_related(order(number, text=text, governor=governor)))

    def test_what_the_order_itself_did_is_kept(self):
        note = ("Governor Jon S. Corzine Return to EO Index This Executive Order extended EO #208 (Kean), EO #35 and "
                "#90 (Florio) and was extended by EO #7 Corzine")
        self.assertEqual(nj.clean_archive_text(note), "This Executive Order extended EO #208 (Kean), EO #35 and #90 (Florio)")


class MutualAidTests(unittest.TestCase):
    def test_a_declaration_to_send_aid_elsewhere_is_not_a_new_jersey_weather_event(self):
        self.assertFalse(nj.is_weather_related(order("233", text=EO_233, governor="Christie")))
        self.assertTrue(nj.is_weather_related(order("409", text=EO_409)))


class RelinkTests(unittest.TestCase):
    def test_swapped_documents_go_back_to_their_orders(self):
        blizzard = "EXECUTIVE ORDER NO. 221 WHEREAS, beginning in the evening on Monday, March 13, 2017, a winter storm"
        gaming = "EXECUTIVE ORDER NO. 222 WHEREAS, on February 3, 2010, I signed Executive Order No. 11 (2010)"
        water = "EXECUTIVE ORDER NO. 106 WHEREAS, New Jersey has suffered substantial damage from Hurricane Sandy"
        orders = [order("221", text=gaming, governor="Christie"), order("222", text=blizzard, governor="Christie"),
                  order("105", text=water, governor="Christie"), order("106", text=water, governor="Christie")]
        self.assertEqual(nj.relink_documents(orders), 2)
        self.assertEqual([o.document_text for o in orders], [blizzard, gaming, water, water])   # no EO 105 to give
        self.assertEqual(nj.document_number("State of New Jersey Executive Order #73 Governor James J. Florio"), "73")
        self.assertIsNone(nj.document_number("WHEREAS, Executive Order No. 45 was issued"))


class TerminationRelationshipTests(unittest.TestCase):
    def test_each_ended_order_is_found_with_its_year(self):
        self.assertEqual(nj.ended_orders(EO_410), [("409", "2025")])
        self.assertEqual(nj.ended_orders(EO_415), [("73", "2011"), ("104", "2012"), ("259", "2021"), ("103", "2020")])
        self.assertEqual(nj.ended_orders(EO_114), [("108", "2012")])
        self.assertEqual(nj.ended_orders(WHITMAN_102), [("98", None)])   # not EO 100, named after the verb
        self.assertEqual(nj.ended_orders(EO_409), [])   # a declaration ends nothing

    def test_targets_resolve_to_the_right_administration_and_get_an_end_date(self):
        christie_73 = order("73", "Declares a State of Emergency", governor="Christie", date="2011-08-25")
        murphy_73 = order("73", "Climate order", governor="Murphy", date="2019-07-01")
        declaration = order("409", text=EO_409, date="2025-12-26")
        ending = order("410", text=EO_410, date="2025-12-30")
        sweep = order("415", text=EO_415, date="2026-01-16")
        orders = [christie_73, murphy_73, declaration, ending, sweep]
        resolve = nj.order_resolver(orders)
        rows = [r for o in orders for r in nj.extract_relationships(o, resolve)]
        pairs = {(r["source_order_id"], r["target_order_id"]) for r in rows if r["relationship_type"] == "terminates"}
        self.assertIn(("NJ-MURPHY-EO-410", "NJ-MURPHY-EO-409"), pairs)
        self.assertIn(("NJ-MURPHY-EO-415", "NJ-CHRISTIE-EO-73"), pairs)
        self.assertNotIn(("NJ-MURPHY-EO-415", "NJ-MURPHY-EO-73"), pairs)
        nj.apply_termination_end_dates(orders, rows)
        self.assertEqual(declaration.end_date, "2025-12-30")
        self.assertEqual(christie_73.end_date, "2026-01-16")


class JoinFileTests(unittest.TestCase):
    def test_only_new_jersey_weather_declarations_reach_the_join(self):
        orders = [order("409", text=EO_409, date="2025-12-26"), order("410", text=EO_410),
                  order("315", "Governor Murphy Signs Executive Order to Accelerate Target Of 100% Clean Energy",
                        text=EO_315, date="2023-02-15"),
                  order("233", text=EO_233, governor="Christie", date="2017-09-29")]
        for o in orders:
            o.action_type = nj.classify_action_type(o)
            o.weather_related = nj.is_weather_related(o)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "declarations_for_join.csv"
            nj.write_join_csv(orders, str(path))
            with path.open(encoding="utf-8") as handle:
                ids = [row["declaration_id"] for row in csv.DictReader(handle)]
        self.assertEqual(ids, ["NJ-MURPHY-EO-409"])


if __name__ == "__main__":
    unittest.main()
