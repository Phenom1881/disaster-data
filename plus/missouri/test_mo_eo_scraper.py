"""Offline regression tests using captured official archive HTML."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import mo_eo_scraper as scraper
import missouri as wrapper
from _adapter_support import signed_date, decide, make_record, write_csv, JOIN_FIELDS

BASE = Path(__file__).parent
class ArchiveTests(unittest.TestCase):
    def test_live_archive_fixture(self):
        content = (BASE / 'fixtures/archive.html').read_text()
        records = scraper.parse_archive(content, 'https://www.sos.mo.gov/library/reference/orders/2000/eo2000', 2000)
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
        record = make_record('MO', 'EXECUTIVE ORDER Extending Executive Order D 2020 168 Declaring that Conditions of Extreme Fire Hazard Exist', json.loads((BASE / 'fixtures/expected_record.json').read_text())['archive_record_url'], signed='2020-09-18')
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
            self.assertEqual(Path(cmd[1]).name, 'mo_eo_scraper.py')
            self.assertEqual(cmd[2::2], ['--actions-out', '--relationships-out', '--join-out'])
            self.assertEqual(wrapper.STATE, 'MO')
            self.assertEqual(path.name, 'declarations_for_join.csv')
            self.assertTrue(note)

    def test_csv_schema_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.csv'
            write_csv(path, JOIN_FIELDS, [])
            self.assertEqual(path.read_bytes(), (','.join(JOIN_FIELDS)+'\n').encode())

if __name__ == '__main__':
    unittest.main()
