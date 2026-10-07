"""NOAA publishes Storm Events months late; declarations signed after the
newest published record must read as pending, not as zero matches."""
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("build_plus", HERE / "build-plus.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


class NoaaPendingTests(unittest.TestCase):
    def test_status(self):
        self.assertEqual(bp.noaa_status(3, "2026-09-30", "2026-06-29"), "matched")
        self.assertEqual(bp.noaa_status(0, "2026-09-30", "2026-06-29"), "pending")
        self.assertEqual(bp.noaa_status(0, "2026-06-01", "2026-06-29"), "none")
        self.assertEqual(bp.noaa_status(0, "2026-09-30", ""), "none")

    def test_data_through_reads_latest_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for slug, dates in (("a", ["2019-06-15 13:30:00", "2024-02-01 00:00:00"]),
                                ("b", ["2026-06-29 08:00:00"])):
                folder = root / "plus" / slug
                folder.mkdir(parents=True)
                with (folder / "eo_storm_matches.csv").open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["declaration_id", "BEGIN_DATE_TIME"])
                    writer.writeheader()
                    writer.writerows({"declaration_id": "x", "BEGIN_DATE_TIME": d} for d in dates)
            self.assertEqual(bp.noaa_data_through(root), "2026-06-29")
            self.assertEqual(bp.noaa_data_through(root / "missing"), "")

    def test_pending_row_renders_as_pending(self):
        bp.NOAA_DATA_THROUGH = "2026-06-29"
        try:
            action = {"declaration_id": "NM-1", "date_signed": "2026-09-30", "title": "Flooding"}
            rows = bp.build_crosswalk([action], [], {})
            self.assertEqual(rows[0]["noaa_status"], "pending")
            html = bp.crosswalk_rows(rows)
            self.assertIn("Pending", html)
            self.assertIn("not published storm data", html)
        finally:
            bp.NOAA_DATA_THROUGH = ""


if __name__ == "__main__":
    unittest.main()
