import csv,tempfile,unittest
from unittest import mock
import sc_eo_scraper as sc

class Tests(unittest.TestCase):
    def test_original_and_narrow_action(self):
        original=sc.Action("2023-29","Declaring a State of Emergency due to Hurricane Idalia","2023-08-29","Henry McMaster","u","s")
        narrow=sc.Action("2023-31","Authorizing Leave with Pay Due to Hurricane Idalia","2023-09-14","Henry McMaster","u","s")
        self.assertEqual(sc.classify(original),"declaration"); self.assertEqual(sc.classify(narrow),"administrative")
    def test_join_schema(self):
        a=sc.Action("2009-04","This executive order declares a state of emergency due to wildfires.","2009-04-23","Mark Sanford","u","s")
        with tempfile.TemporaryDirectory() as d:
            p=[f"{d}/{x}.csv" for x in "arj"]; sc.write_outputs([a],*p)
            with open(p[2],encoding="utf-8") as h: rows=list(csv.DictReader(h))
        self.assertEqual(len(rows),1); self.assertEqual(list(rows[0]),list(sc.JOIN_FIELDS))


GOVERNOR_FIXTURE = """
<div>
<p><a href="/sites/governor/files/Documents/Executive-Orders/2025-01-10%20FILED%20Executive%20Order%20No.%202025-02.pdf">2025-02 Official (PDF)</a> |
<a href="/sites/governor/files/Documents/Executive-Orders/2025-01-10%20Text%20Alternative%202025-02.pdf">Text Alternative (PDF)</a> - Declaring a State of Emergency to Address Winter Weather</p>
<p><a href="/sites/governor/files/Documents/Executive-Orders/2024-11-07%20eFILED%20Executive%20Order%20No.%202024-33%20-%20State%20of%20Emergency%20to%20Address%20Flooding%20%26%20Other%20Dangerous%20Conditions.pdf">2024-33 Official (PDF)</a> | - Declare State of Emergency to Address Flooding and Other Dangerous Conditions</p>
<p><a href="/sites/governor/files/Documents/Executive-Orders/2019-08-31%20FILED%20Executive%20Order%20No.%202019-26%20-%20Declaring%20State%20of%20Emergency%20Due%20to%20Hurricane%20Dorian.pdf">2019-26 - Official (PDF)</a></p>
<p><a href="/sites/governor/files/Documents/Executive-Orders/2017-20-Declaring-State-of-Emergency-to-Prepare-for-Hurricane-Irma.pdf">2017-20 - Official (PDF)</a></p>
<p><a href="/sites/governor/files/Documents/Executive-Orders/2017-10.pdf">2017-10 - Official (PDF)</a></p>
</div>
"""


class FileNameTests(unittest.TestCase):
    def test_a_file_name_gives_the_description(self):
        cases = {
            "/x/2019-08-31%20FILED%20Executive%20Order%20No.%202019-26%20-%20Declaring%20State%20of%20Emergency%20Due%20to%20Hurricane%20Dorian.pdf":
                "Declaring State of Emergency Due to Hurricane Dorian",
            "/x/2017-20-Declaring-State-of-Emergency-to-Prepare-for-Hurricane-Irma.pdf":
                "Declaring State of Emergency to Prepare for Hurricane Irma",
            "/x/EO-2018-26-Declaring-a-State-of-Emergency.pdf": "Declaring a State of Emergency",
            "/x/2018-09-08-Executive-Order-No-2018-27-Suspending-Certain-Motor-Vehicle-Regulations-Due-to-Emergency.pdf":
                "Suspending Certain Motor Vehicle Regulations Due to Emergency",
            "/x/2019-09-01%20FINAL%20Executive%20Order%20No.%202019-28%20-%20General%20Population%20Evacuation%20Due%20to%20Hurricane%20Dorian%20ADA.pdf":
                "General Population Evacuation Due to Hurricane Dorian",
            "/x/2019-09-01%20FINAL%20Executive%20Order%20No.%202019-29%20-%20State%20Gov&apos;t%20Office%20Closures.pdf":
                "State Gov't Office Closures",
        }
        for href, expected in cases.items():
            self.assertEqual(sc.file_description(href), expected, href)

    def test_a_file_name_without_a_description_gives_nothing(self):
        for href in ("/x/2017-10.pdf", "/x/Scanned%20from%20ECOS%20XR%20SH119.pdf",
                     "/x/FILED%20Executive%20Order%20No.%202017-30.pdf",
                     "/x/S.C.%202020%20Census%20Complete%20Count%20Committee%20-%20OCR.pdf"):
            self.assertEqual(sc.file_description(href), "", href)


class GovernorPageTests(unittest.TestCase):
    def setUp(self):
        self.page = sc.page_descriptions(GOVERNOR_FIXTURE)

    def test_text_after_the_link_is_the_description(self):
        self.assertEqual(self.page["2024-33"][0],
                         "Declare State of Emergency to Address Flooding and Other Dangerous Conditions")
        self.assertEqual(self.page["2025-02"][0], "Declaring a State of Emergency to Address Winter Weather")

    def test_a_link_label_is_not_a_description(self):
        # "2019-26 - Official (PDF)" once gave the description "Official (PDF)".
        self.assertEqual(self.page["2019-26"][0], "Declaring State of Emergency Due to Hurricane Dorian")
        self.assertEqual(self.page["2017-20"][0], "Declaring State of Emergency to Prepare for Hurricane Irma")
        self.assertEqual(self.page["2017-10"][0], "")

    def test_dates_come_from_the_file_name(self):
        self.assertEqual(self.page["2025-02"][1], "2025-01-10")
        self.assertEqual(self.page["2017-20"][1], "")

    def test_orders_the_state_library_lacks_are_added(self):
        added = sc.governor_only(self.page, {"2024-33", "2019-26"})
        self.assertEqual([a.number for a in added], ["2025-02"])   # 2017-10 and 2017-20 have no date
        self.assertEqual(added[0].date, "2025-01-10")
        self.assertTrue(added[0].url.startswith("https://www.governor.sc.gov/sites/governor/files/"))
        self.assertEqual(sc.classify(added[0]), "declaration")


class ClassifyTests(unittest.TestCase):
    def action(self, description, subjects=""):
        return sc.Action("2099-01", description, "2099-01-01", "Henry McMaster", "u", "s", subjects)

    def test_a_title_that_is_the_state_of_emergency_is_a_declaration(self):
        for text in ("State of Emergency Due to Severe Winter Weather",
                     "State of Emergency to Address Flooding & Other Dangerous Conditions",
                     "Declare State of Emergency to Address Flooding and Other Dangerous Conditions",
                     "declares that a State of Emergency exists in South Carolina in response to Hurricane Matthew"):
            self.assertEqual(sc.classify(self.action(text)), "declaration", text)

    def test_orders_issued_under_a_state_of_emergency_are_not(self):
        cases = {
            "Authorizing Leave with Pay Due to State of Emergency Hurricane Helene Related Impacts": "administrative",
            "Granting Paid Leave to State Employees Due to State of Emergency": "administrative",
            "has declared a State of Emergency and orders an evacuation of all persons": "administrative",
            "Suspending Transportation Regulations Due to NC State of Emergency": "administrative",
            "Rescinding Evacuations & Closures for Beaufort, Jasper, & Colleton Counties": "termination",
        }
        for text, expected in cases.items():
            self.assertEqual(sc.classify(self.action(text)), expected, text)

    def test_the_subject_is_added_in_parentheses(self):
        a = sc.Action("2018-26", "Declaring a State of Emergency", "2018-09-08", "Henry McMaster", "u", "s",
                      "Executive orders--South Carolina; Hurricane Florence, 2018")
        with tempfile.TemporaryDirectory() as d:
            p = [f"{d}/{x}.csv" for x in "arj"]; sc.write_outputs([a], *p)
            with open(p[2], encoding="utf-8") as h: rows = list(csv.DictReader(h))
        self.assertEqual(rows[0]["event_description"], "Declaring a State of Emergency (Hurricane Florence, 2018)")
        self.assertNotIn("\u2014", rows[0]["event_description"])


class CollectTests(unittest.TestCase):
    def test_an_abstract_stands_in_for_a_missing_description(self):
        item = {"uuid": "f8f65301-3400-4657-986b-d79a156728f9", "metadata": {
            "dc.title": [{"value": "Executive order no. 2016-26"}],
            "dc.date.issued": [{"value": "2016-10-04"}],
            "dc.subject": [{"value": "Executive orders--South Carolina"}, {"value": "Hurricane Matthew, 2016"}],
            "dc.description.abstract": [{"value": "This executive order by Governor Nikki R. Haley declares that a "
                                                  "State of Emergency exists in South Carolina."}],
            "dc.identifier.uri": [{"value": "http://hdl.handle.net/10827/23222"}],
        }}
        api = {"_embedded": {"searchResult": {"page": {"totalPages": 1}, "_embedded": {"objects": [
            {"_embedded": {"indexableObject": item}}]}}}}

        def fake_get(url, **kwargs):
            response = mock.Mock()
            response.raise_for_status = lambda: None
            response.text = GOVERNOR_FIXTURE
            response.json = lambda: api
            return response

        with mock.patch.object(sc.requests, "get", side_effect=fake_get):
            actions = {a.number: a for a in sc.collect()}
        self.assertIn("declares that a State of Emergency exists", actions["2016-26"].description)
        self.assertEqual(sc.classify(actions["2016-26"]), "declaration")
        self.assertIn("2025-02", actions)   # on the Governor's page only
        with tempfile.TemporaryDirectory() as d:
            p = [f"{d}/{x}.csv" for x in "arj"]; sc.write_outputs([actions["2016-26"]], *p)
            with open(p[2], encoding="utf-8") as h: rows = list(csv.DictReader(h))
        self.assertEqual([r["declaration_id"] for r in rows], ["SC-EO-2016-26"])


if __name__=="__main__": unittest.main()
