import csv
import tempfile
import unittest
from pathlib import Path

import ms_eo_scraper as ms


def post(title,date="2023-03-25",content=""):
    return {"id":1,"date":date+"T12:00:00","link":"https://governorreeves.ms.gov/test/","title":{"rendered":title},"content":{"rendered":content}}


class MississippiScraperTests(unittest.TestCase):
    def test_weather_declaration_parses(self):
        action=ms.parse_post(post("Governor Reeves Issues State of Emergency Following Severe Storms"))
        self.assertEqual(ms.classify(action),"declaration")
        self.assertIsNotNone(ms.HAZARD_RE.search(action.title))

    def test_public_health_declaration_is_not_weather(self):
        action=ms.parse_post(post("Governor Tate Reeves Declares State of Emergency to Protect Public Health","2020-03-14"))
        self.assertIsNone(ms.HAZARD_RE.search(action.title))

    def test_extension_is_excluded_from_join(self):
        original=ms.parse_post(post("Governor Reeves Issues State of Emergency Ahead of Hurricane Ida","2021-08-29"))
        extension=ms.parse_post(post("Governor Reeves Extends State of Emergency Ahead of Hurricane Ida","2021-09-10"))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); ms.write_outputs([original,extension],root/"a.csv",root/"r.csv",root/"j.csv")
            with open(root/"j.csv",encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1)


if __name__ == "__main__": unittest.main()
