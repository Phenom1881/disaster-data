"""Offline regression tests using captured official archive HTML."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import co_eo_scraper as scraper
import colorado as wrapper
from _adapter_support import signed_date, decide, make_record, write_csv, JOIN_FIELDS

BASE = Path(__file__).parent
class ArchiveTests(unittest.TestCase):
    def test_live_archive_fixture(self):
        content = (BASE / 'fixtures/archive.html').read_text()
        records = scraper.parse_archive(content, 'https://spl.cde.state.co.us/artemis/goserials/go4312internet/', 'Jared Polis')
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
        record = make_record('CO', 'EXECUTIVE ORDER Extending Executive Order D 2020 168 Declaring that Conditions of Extreme Fire Hazard Exist', json.loads((BASE / 'fixtures/expected_record.json').read_text())['archive_record_url'], signed='2020-09-18')
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
            self.assertEqual(Path(cmd[1]).name, 'co_eo_scraper.py')
            self.assertEqual(cmd[2::2], ['--actions-out', '--relationships-out', '--join-out'])
            self.assertEqual(wrapper.STATE, 'CO')
            self.assertEqual(path.name, 'declarations_for_join.csv')
            self.assertTrue(note)

    def test_csv_schema_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.csv'
            write_csv(path, JOIN_FIELDS, [])
            self.assertEqual(path.read_bytes(), (','.join(JOIN_FIELDS)+'\n').encode())

class HandAddedDeclarationTests(unittest.TestCase):
    @staticmethod
    def rows(name):
        import csv
        with open(Path(__file__).parent / name, newline='', encoding='utf-8') as handle:
            return list(csv.DictReader(handle))

    def test_dates_and_quoted_sources(self):
        rows = self.rows('manual_declarations.csv')
        self.assertEqual({r['declaration_id']: r['date_signed'] for r in rows},
                         {'CO-EO-D-2006-026': '2006-12-28', 'CO-EO-D-2023-011': '2023-07-21',
                          'CO-SOE-2026-06-28': '2026-06-28', 'CO-SOE-2026-06-29': '2026-06-29'})
        notes = {r['declaration_id']: r for r in self.rows('hazard_overrides.csv')}
        for row in rows:
            self.assertEqual(notes[row['declaration_id']]['source_url'], row['archive_record_url'])
            self.assertIn("'", notes[row['declaration_id']]['review_note'])

    def test_a_refresh_keeps_the_memorializing_order_and_its_date(self):
        from _adapter_support import merge_overrides
        reviews = json.loads((Path(__file__).parent / 'review_decisions.json').read_text())
        self.assertEqual(reviews['CO-EO-D-2023-011']['decision'], 'include')
        generated = [dict(declaration_id=k, hazard_category_override=v['hazard_category_override'],
                          review_note=v.get('reason', ''), source_url=v.get('source_url', ''))
                     for k, v in reviews.items() if v.get('hazard_category_override')]
        collected = {r['declaration_id'] for r in self.rows('declarations_for_join.csv')} | {'CO-EO-D-2023-011'}
        rows, _ = merge_overrides(Path(__file__).parent / 'hazard_overrides.csv', generated, collected)
        self.assertEqual({r['declaration_id']: r.get('event_date') for r in rows}.get('CO-EO-D-2023-011'), '2023-06-22')

if __name__ == '__main__':
    unittest.main()
