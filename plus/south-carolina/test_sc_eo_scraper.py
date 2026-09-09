import csv,tempfile,unittest
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
if __name__=="__main__": unittest.main()
