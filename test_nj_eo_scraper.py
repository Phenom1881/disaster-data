import unittest

from bs4 import BeautifulSoup

import nj_eo_scraper as nj


class NewJerseyRoundThreeTests(unittest.TestCase):
    def test_shifted_date_cell(self):
        soup = BeautifulSoup(
            '<table><tr><td><a href="eo109.pdf">109</a></td>'
            '<td>11/03/2012</td></tr></table>',
            "html.parser",
        )
        row = nj._extract_order_rows(soup, "https://www.nj.gov/x/")[0]
        self.assertEqual(row[0], "109")
        self.assertEqual(row[1], "")
        self.assertEqual(row[2], "2012-11-03")

    def test_relationship_cell_is_not_date(self):
        soup = BeautifulSoup(
            '<table><tr><td><a href="eow46.htm">46</a></td>'
            '<td>Terminates the state of emergency declared by EO 45.</td>'
            '<td>Terminates EO #45 Whitman</td></tr></table>',
            "html.parser",
        )
        row = nj._extract_order_rows(soup, "https://www.nj.gov/x/")[0]
        self.assertIsNone(row[2])

    def test_signature_date_recovery(self):
        text = (
            "GIVEN, under my hand and seal this 12th day of January in the "
            "Year of Our Lord, One Thousand Nine Hundred and Ninety Six, "
            "and of the Independence of the United States."
        )
        self.assertEqual(nj.recover_signature_date(text), "1996-01-12")

    def test_blank_signature_stays_undated(self):
        self.assertIsNone(
            nj.recover_signature_date(
                "GIVEN, under my hand and seal this day of in the Year of Our Lord"
            )
        )

    def test_appendix_does_not_replace_real_order(self):
        soup = BeautifulSoup(
            '<table><tr><td><a href="EO-3-Appendix-A.pdf">3 App. A</a></td>'
            '<td>Code</td><td>01/20/2026</td></tr>'
            '<tr><td><a href="EO-3.pdf">3</a></td>'
            '<td>Outlining Ethics and Standards</td><td>01/20/2026</td>'
            '</tr></table>',
            "html.parser",
        )
        rows = nj._extract_order_rows(soup, "https://www.nj.gov/x/")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][3].endswith("EO-3.pdf"))

    def test_global_relationship_dedup(self):
        row = {
            "source_order_id": "NJ-FLORIO-EO-48",
            "target_order_id": "NJ-FLORIO-EO-46",
            "relationship_type": "terminates",
            "relationship_text": "terminates EO 46",
            "relationship_source": "document_text",
            "confidence": "medium",
        }
        self.assertEqual(len(nj.dedupe_relationships([row, dict(row)])), 1)


if __name__ == "__main__":
    unittest.main()
