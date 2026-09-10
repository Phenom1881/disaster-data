import csv, tempfile, unittest
import la_eo_scraper as la

FIXTURE='''<a href="/media/a.pdf">JBE 21-10 State of Emergency--Hurricane Ida</a><a href="/media/b.pdf">JBE 21-11 Renewal of State of Emergency--Hurricane Ida</a>'''

class LouisianaTests(unittest.TestCase):
    def test_index_and_modifier_exclusion(self):
        actions=la.parse_index(FIXTURE,la.ARCHIVE_URL)
        self.assertEqual(actions[0].number,"JBE 21-10")
        enriched=[la.Action(a.number,a.description,a.url,"2021-08-26",a.description) for a in actions]
        with tempfile.TemporaryDirectory() as root:
            paths=[root+f"/{n}.csv" for n in ("actions","rels","join")]; la.write_outputs(enriched,*paths)
            with open(paths[2],encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(list(rows[0]),list(la.JOIN_FIELDS)); self.assertEqual(len(rows),1)
    def test_no_overrides(self): self.assertEqual(la.HAZARD_OVERRIDES,{})
    def test_untitled_renewal_detected_from_official_text(self):
        action=la.Action("JML 24-147","State of Emergency Hurricane Francine","u","2024-09-18","Governor declared a state of emergency on September 9, 2024, in JML 24-142")
        self.assertEqual(la.classify(action),"extension")

if __name__=="__main__": unittest.main()
