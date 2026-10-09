"""A record reviewed as not a weather event is dropped from the listed actions."""
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("build_plus", str(Path(__file__).parent / "build-plus.py"))
bp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bp)

FIELDS = ["declaration_id", "governor", "eo_number", "event_description", "date_signed", "archive_record_url"]


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


class ExcludedRecordsTests(unittest.TestCase):
    def test_excluded_ids_come_from_the_override_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(bp.excluded_declaration_ids(folder), set())
            write(folder / "hazard_overrides.csv",
                  ["declaration_id", "hazard_category_override", "review_note", "source_url"],
                  [{"declaration_id": "X-1", "hazard_category_override": "Exclude"},
                   {"declaration_id": "X-2", "hazard_category_override": "flood"},
                   {"declaration_id": "X-3", "hazard_category_override": " exclude "}])
            self.assertEqual(bp.excluded_declaration_ids(folder), {"X-1", "X-3"})

    def test_excluded_record_is_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder / "declarations_for_join.csv", FIELDS, [
                {"declaration_id": "KS-1", "governor": "G", "eo_number": "1",
                 "event_description": "Tornado", "date_signed": "2025-05-01", "archive_record_url": "u"},
                {"declaration_id": "KS-2", "governor": "G", "eo_number": "2",
                 "event_description": "Fuel Shortage", "date_signed": "2025-04-30", "archive_record_url": "u"},
            ])
            write(folder / "hazard_overrides.csv",
                  ["declaration_id", "hazard_category_override", "review_note", "source_url"],
                  [{"declaration_id": "KS-2", "hazard_category_override": "exclude"}])
            state = {"abbreviation": "KS", "name": "Kansas", "slug": "kansas",
                     "action_files": ["declarations_for_join.csv"]}
            actions, _ = bp.load_state_actions(state, folder)
            self.assertEqual([a["declaration_id"] for a in actions], ["KS-1"])


if __name__ == "__main__":
    unittest.main()
