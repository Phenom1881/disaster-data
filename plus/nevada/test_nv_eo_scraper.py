import csv, tempfile, unittest
import nv_eo_scraper as nv

class NevadaTests(unittest.TestCase):
    def test_executive_listing(self):
        rows=nv.parse_listing('<a href="/executive-actions/executive-orders/2024-executive-orders/a/">EO 2024-003 - Ordering Flags</a>',nv.EO_ROOT,"executive_order")
        self.assertEqual(rows[0][:2],("2024-003","Ordering Flags"))
    def test_emergency_listing(self):
        rows=nv.parse_listing('<a href="/executive-actions/emergency-orders/2024-emergency-orders/davis/">Declaration of Emergency The Davis Fire</a>',nv.EMERGENCY_ROOT,"emergency_order")
        self.assertTrue(rows[0][0].startswith("EMERGENCY-"))
    def test_signature_date_beats_recital(self):
        text="August 10, 2026 fire began. IN WITNESS WHEREOF, this 27th day of August, in the year two thousand twenty-six."
        self.assertEqual(nv.extract_date(text,"2026"),"2026-08-27")
    def test_original_join_amendment_excluded(self):
        original=nv.Action("EMERGENCY-DAVIS","Declaration of Emergency The Davis Fire","2024-09-08","https://example.gov/davis","state of emergency due to the Davis wildfire","emergency_order")
        amended=nv.Action("EMERGENCY-DAVIS-AMENDED","Declaration of Emergency The Davis Fire (Amended)","2024-09-08","https://example.gov/amended","state of emergency due to the Davis wildfire","emergency_order")
        with tempfile.TemporaryDirectory() as root:
            paths=[root+"/"+n for n in ("a.csv","r.csv","j.csv")]; nv.write_outputs([original,amended],*paths)
            with open(paths[2],encoding="utf-8") as handle: rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),1); self.assertEqual(tuple(rows[0]),nv.JOIN_FIELDS)
    def test_no_overrides(self): self.assertEqual(nv.HAZARD_OVERRIDES,{})
if __name__=="__main__": unittest.main()
