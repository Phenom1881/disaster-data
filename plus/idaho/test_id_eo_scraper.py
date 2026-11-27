"""Offline regression tests using captured official archive HTML."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import id_eo_scraper as scraper
import idaho as wrapper
from _adapter_support import signed_date, decide, make_record, write_csv, JOIN_FIELDS

BASE = Path(__file__).parent
class ArchiveTests(unittest.TestCase):
    def test_live_archive_fixture(self):
        content = (BASE / 'fixtures/archive.html').read_text()
        records = scraper.parse_drought(content, 'https://idwr.idaho.gov/legal-matters/drought-declarations/')
        expected = json.loads((BASE / 'fixtures/expected_record.json').read_text())
        actual = next(r for r in records if r['declaration_id'] == expected['declaration_id'])
        for key, value in expected.items():
            self.assertEqual(actual[key], value, key)
        self.assertGreaterEqual(len(records), 2)

    def test_signature_not_update_or_event_date(self):
        self.assertEqual(signed_date('Updated: December 7, 2018. Storm began June 8, 2010.'), ('', ''))
        self.assertEqual(signed_date('Given under my hand this 16th day of March, 2021.')[0], '2021-03-16')
        self.assertEqual(signed_date('Given this 17th of June 2022.')[0], '2022-06-17')
        self.assertEqual(signed_date('GIVEN this _____ day of May, 2001.'), ('', ''))

    def test_classification_boundaries(self):
        record = make_record('ID', 'EXECUTIVE ORDER Extending Executive Order D 2020 168 Declaring that Conditions of Extreme Fire Hazard Exist', json.loads((BASE / 'fixtures/expected_record.json').read_text())['archive_record_url'], signed='2020-09-18')
        self.assertEqual(decide(record)[0], 'companion')
        record['event_description'] = 'Declaring a disaster emergency due to severe winter storms'
        record['date_signed'] = ''
        self.assertEqual(decide(record)[0], 'review')
        record['event_description'] = 'Declaring a COVID-19 emergency'
        self.assertEqual(decide(record)[0], 'exclude')

    def test_wrapper_contract(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(wrapper.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            run.return_value.stderr = ''
            path, note = wrapper.collect(directory)
            cmd = run.call_args.args[0]
            self.assertEqual(Path(cmd[1]).name, 'id_eo_scraper.py')
            self.assertEqual(cmd[2::2], ['--actions-out', '--relationships-out', '--join-out'])
            self.assertEqual(wrapper.STATE, 'ID')
            self.assertEqual(path.name, 'declarations_for_join.csv')
            self.assertTrue(note)

    def test_csv_schema_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.csv'
            write_csv(path, JOIN_FIELDS, [])
            self.assertEqual(path.read_bytes(), (','.join(JOIN_FIELDS)+'\n').encode())

class HandAddedDeclarationTests(unittest.TestCase):
    """manual_declarations.csv: Governor declarations announced by IOEM or the news, not in the order archive."""

    def test_each_row_is_dated_sourced_and_not_already_collected(self):
        import csv
        from datetime import date
        here = Path(__file__).resolve().parent
        with (here / 'manual_declarations.csv').open(encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        with (here / 'id_emergency_actions_all.csv').open(encoding='utf-8') as handle:
            collected = {row['declaration_id'] for row in csv.DictReader(handle)}
        self.assertTrue(rows)
        self.assertEqual(len({row['declaration_id'] for row in rows}), len(rows))
        for row in rows:
            self.assertEqual(row['declaration_id'], 'ID-SOE-' + row['date_signed'])
            date.fromisoformat(row['date_signed'])
            self.assertNotIn(row['declaration_id'], collected)
            self.assertTrue(row['governor'])
            # IOEM and news releases, and the Legislative Services Office's list
            # of the Governor's COVID-19 proclamations.
            self.assertTrue(row['archive_record_url'].startswith(('https://ioem.idaho.gov/', 'https://kivitv.com/',
                                                                  'https://legislature.idaho.gov/')),
                            row['declaration_id'])

    def test_the_covid_19_extension_matches_the_january_2021_windstorm_only_by_date(self):
        # The COVID-19 emergency declaration, extended December 31, 2020, was in
        # force when straight-line winds struck north Idaho on January 13, 2021.
        import csv
        import importlib.util
        here = Path(__file__).resolve().parent
        url = ('https://legislature.idaho.gov/wp-content/uploads/sessioninfo/2025/interim/'
               '251001_covid_05_Covid%20Emerg%20Orders%20Extensions.pdf')
        with (here / 'manual_declarations.csv').open(encoding='utf-8') as handle:
            row = next(r for r in csv.DictReader(handle) if r['declaration_id'] == 'ID-SOE-2020-12-31')
        with (here / 'hazard_overrides.csv').open(encoding='utf-8') as handle:
            note = next(r for r in csv.DictReader(handle) if r['declaration_id'] == 'ID-SOE-2020-12-31')
        self.assertEqual((row['governor'], row['date_signed'], row['archive_record_url']), ('Brad Little', '2020-12-31', url))
        self.assertIn('straight-line windstorm', row['event_description'])
        self.assertIn('matches DR-4589 only by date', row['event_description'])
        self.assertEqual((note['hazard_category_override'], note['source_url']), ('wind', url))
        self.assertIn("'12/31/2020', 'Emergency Declaration Extension'", note['review_note'])
        self.assertIn('flagged as a date-only match for a different hazard', note['review_note'])
        spec = importlib.util.spec_from_file_location('idaho_adapter_windstorm', here / 'idaho.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        source = (here / 'idaho.py').read_text(encoding='utf-8')
        self.assertIn('the January 13, 2021 north Idaho windstorm (DR-4589) counts as matched only because the '
                      "Governor's COVID-19 emergency declaration, extended on December 31, 2020, was in force", source)
        self.assertIn('ID-SOE-2020-12-31', adapter.CAPABILITIES['known_gaps'][-1])


if __name__ == '__main__':
    unittest.main()
