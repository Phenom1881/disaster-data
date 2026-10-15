"""Tests for gen_plus_sidecar.py's state totals.

Run from the repo root or scripts/:  python -m unittest test_gen_plus_sidecar
"""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gen_plus_sidecar", ROOT / "gen_plus_sidecar.py")
sidecar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecar)

JOIN_FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]
SEVERITY_FIELDS = JOIN_FIELDS + ["CZ_TYPE", "area_type", "CZ_FIPS", "CZ_NAME", "deaths_direct", "injuries_direct",
                                 "damage_property_usd", "damage_crops_usd", "event_types", "event_count", "total_damage_usd"]


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def declaration(ident, date):
    return {"declaration_id": ident, "governor": "Katie Hobbs", "eo_number": "", "event_description": f"Emergency {ident}",
            "date_signed": date, "archive_record_url": f"https://example.gov/{ident}"}


class StateTotalTests(unittest.TestCase):
    def test_total_is_the_count_the_state_page_shows(self):
        self.assertEqual(sidecar.state_total({"metrics": {"action_count": 59}}, "/nowhere"), 59)
        self.assertEqual(sidecar.state_total({"metrics": {"action_count": 0}}, "/nowhere"), 0)

    def test_summary_without_a_count_falls_back_to_the_join_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(Path(tmp) / "declarations_for_join.csv", JOIN_FIELDS,
                      [declaration("AZ-1", "2025-10-19"), declaration("AZ-2", "2025-09-27")])
            self.assertEqual(sidecar.state_total({"metrics": {}}, tmp), 2)
            self.assertEqual(sidecar.state_total({"metrics": {"action_count": True}}, tmp), 2)   # not a count
            self.assertEqual(sidecar.state_total({}, tmp), 2)

    def test_a_county_never_shows_more_matches_than_the_state_total(self):
        # Arizona keeps most of its declarations in manual_declarations.csv.
        # The storm matches cover all of them, so the total must too; counting
        # the join file alone gave Maricopa County "23 matched of 6".
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "arizona"
            state_dir.mkdir()
            write_csv(state_dir / "declarations_for_join.csv", JOIN_FIELDS, [declaration("AZ-1", "2025-10-19")])
            manual = [declaration("AZ-M1", "2024-08-01"), declaration("AZ-M2", "2023-07-15"), declaration("AZ-M3", "2022-03-02")]
            write_csv(state_dir / "manual_declarations.csv", JOIN_FIELDS, manual)
            matched = [declaration("AZ-1", "2025-10-19")] + manual
            write_csv(state_dir / "eo_storm_severity_summary.csv", SEVERITY_FIELDS, [
                dict(row, CZ_TYPE="C", area_type="county", CZ_FIPS="13", CZ_NAME="MARICOPA", deaths_direct="0",
                     injuries_direct="0", damage_property_usd="1000", damage_crops_usd="0", event_types="Flash Flood",
                     event_count="2", total_damage_usd="1000") for row in matched])
            (state_dir / "state-summary.json").write_text(json.dumps({
                "abbreviation": "AZ", "name": "Arizona", "slug": "arizona", "coverage": "test",
                "action_file": "declarations_for_join.csv", "metrics": {"action_count": 4}}), encoding="utf-8")
            by_name, by_squash, _ = sidecar.build_indexes({"04013": {"s": "AZ", "n": "Maricopa"}})
            stats = {"county_rows_seen": 0, "resolved_rows": 0, "unresolved_rows": 0, "zone_rows_skipped": 0,
                     "untyped_rows_skipped": 0, "unresolved_examples": {}, "states_without_evidence": []}
            ab, record = sidecar.collect_state("arizona", str(state_dir), {}, by_name, by_squash, stats)
        self.assertEqual(ab, "AZ")
        self.assertEqual(record["total"], 4)
        self.assertEqual(len(record["counties"]["04013"]), 4)
        self.assertLessEqual(len(record["counties"]["04013"]), record["total"])


if __name__ == "__main__":
    unittest.main()
