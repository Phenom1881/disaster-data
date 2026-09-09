import csv
import tempfile
import unittest
from pathlib import Path

import al_eo_scraper as al


def post(title, date="2023-07-13"):
    return {"title":{"rendered":title},"content":{"rendered":'<a href="/order.pdf">Download</a>'},"link":"https://governor.alabama.gov/newsroom/test/","date":date+"T12:00:00"}


class AlabamaScraperTests(unittest.TestCase):
    def test_embedded_event_date_is_preserved(self):
        action=al.parse_post(post("State of Emergency: June 10, 2023 Severe Weather"),"state_of_emergency")
        self.assertEqual(action.date,"2023-06-10")

    def test_subtropical_storm_is_weather(self):
        action=al.parse_post(post("State of Emergency: Subtropical Storm Alberto","2018-05-26"),"state_of_emergency")
        self.assertEqual(al.classify(action),"declaration")
        self.assertIsNotNone(al.HAZARD_RE.search(action.title))

    def test_supplemental_order_is_excluded_from_join(self):
        original=al.parse_post(post("State of Emergency: Hurricane Ida","2021-08-28"),"state_of_emergency")
        supplement=al.parse_post(post("First Supplemental State of Emergency: Hurricane Ida","2021-09-02"),"state_of_emergency")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); al.write_outputs([original,supplement],root/"a.csv",root/"r.csv",root/"j.csv")
            with open(root/"j.csv",encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1)


if __name__ == "__main__": unittest.main()
