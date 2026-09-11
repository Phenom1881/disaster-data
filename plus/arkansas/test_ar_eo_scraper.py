import csv, tempfile, unittest
import ar_eo_scraper as ar

def post(title,text,date="2024-08-17T12:00:00",ident=1):
    return {"id":ident,"date":date,"link":f"https://governor.arkansas.gov/executive_orders/{ident}/","title":{"rendered":title},"content":{"rendered":text}}

class ArkansasTests(unittest.TestCase):
    def test_official_text_drives_hazard_and_date(self):
        action=ar.parse_post(post("DR 24-06: Emergency declaration for severe thunderstorms and strong winds","I do hereby declare that a state of emergency exists. IN TESTIMONY on this 17 th day of August, 2024."))
        self.assertEqual(action.date,"2024-08-17"); self.assertEqual(ar.classify(action),"declaration")
        with tempfile.TemporaryDirectory() as root:
            paths=[root+f"/{n}.csv" for n in ("actions","rels","join")]; ar.write_outputs([action],*paths)
            with open(paths[2],encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1); self.assertEqual(list(rows[0]),list(ar.JOIN_FIELDS))
    def test_amendment_excluded(self):
        action=ar.parse_post(post("EO 25-03: Executive order amending DR 24-05","Severe storms and tornadoes."))
        self.assertEqual(ar.classify(action),"amendment")
    def test_statute_as_amended_is_not_an_amendment_order(self):
        action=ar.parse_post(post("EO 25-07: Executive order to provide funding as authorized by Ark. Code Ann. 12-75-114, as amended","Severe storms, tornadoes, and flooding are expected. I do hereby declare a state of emergency."))
        self.assertEqual(ar.classify(action),"declaration")
    def test_operational_companion_reference_is_not_declaration(self):
        action=ar.parse_post(post("Executive order to suspend certain requirements for FEMA housing unit transport","Executive Order 23-20 declared a state of emergency after severe thunderstorms and tornadoes."))
        self.assertTrue(action.number.startswith("POST-")); self.assertEqual(ar.classify(action),"administrative")
    def test_no_overrides(self): self.assertEqual(ar.HAZARD_OVERRIDES,{})

if __name__=="__main__": unittest.main()
