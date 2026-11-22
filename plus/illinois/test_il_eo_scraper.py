"""Offline regression tests using captured official archive HTML."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import il_eo_scraper as scraper
import illinois as wrapper
from _adapter_support import signed_date, decide, make_record, write_csv, JOIN_FIELDS

BASE = Path(__file__).parent
class ArchiveTests(unittest.TestCase):
    def test_live_archive_fixture(self):
        content = (BASE / 'fixtures/archive.html').read_text()
        records = scraper.parse_archive(content, 'https://www.illinois.gov/government/disaster-proclamations.html')
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
        record = make_record('IL', 'EXECUTIVE ORDER Extending Executive Order D 2020 168 Declaring that Conditions of Extreme Fire Hazard Exist', json.loads((BASE / 'fixtures/expected_record.json').read_text())['archive_record_url'], signed='2020-09-18')
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
            self.assertEqual(Path(cmd[1]).name, 'il_eo_scraper.py')
            self.assertEqual(cmd[2::2], ['--actions-out', '--relationships-out', '--join-out'])
            self.assertEqual(wrapper.STATE, 'IL')
            self.assertEqual(path.name, 'declarations_for_join.csv')
            self.assertTrue(note)

    def test_csv_schema_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'out.csv'
            write_csv(path, JOIN_FIELDS, [])
            self.assertEqual(path.read_bytes(), (','.join(JOIN_FIELDS)+'\n').encode())

class HandAddedDeclarationTests(unittest.TestCase):
    """manual_declarations.csv and the reviewed event dates in hazard_overrides.csv."""

    @staticmethod
    def rows(name):
        import csv
        with open(BASE / name, newline='', encoding='utf-8') as handle:
            return list(csv.DictReader(handle))

    def test_each_row_is_dated_and_sourced(self):
        rows = self.rows('manual_declarations.csv')
        self.assertEqual(len({r['declaration_id'] for r in rows}), len(rows))
        for row in rows:
            self.assertEqual(row['declaration_id'], 'IL-PROC-' + row['date_signed'])
            self.assertTrue(row['archive_record_url'].startswith('https://'), row['declaration_id'])

    def test_2008_proclamations_and_their_sources(self):
        rows = {r['declaration_id']: r for r in self.rows('manual_declarations.csv')}
        expected = {
            'IL-PROC-2008-02-26': 'obama.senate.gov/press/080226-durbin_obama_ca_2',
            'IL-PROC-2008-03-20': 'idph.illinois.gov/public/press08/3.21.08GovFlood.htm',
            'IL-PROC-2008-06-10': 'climate.isws.illinois.edu/statecli/2008/flood2008/flood.htm',
        }
        for key, source in expected.items():
            self.assertIn(key, rows)
            self.assertTrue(rows[key]['archive_record_url'].endswith(source), key)
            self.assertEqual(rows[key]['governor'], 'Rod Blagojevich', key)

    def test_late_proclamations_are_compared_on_the_storm_they_declare(self):
        dates = {r['declaration_id']: r['event_date'] for r in self.rows('hazard_overrides.csv') if r.get('event_date')}
        self.assertEqual(dates, {'IL-PROC-2008-02-26': '2008-02-05',
                                 'IL-PROC-2024-08-30': '2024-07-13',
                                 'IL-PROC-4883F2AF4F255E59': '2023-09-17'})
        signed = {r['declaration_id']: r['date_signed'] for r in self.rows('manual_declarations.csv') + self.rows('declarations_for_join.csv')}
        for key, day in dates.items():
            self.assertLess(day, signed[key], key)

    def test_a_refresh_keeps_the_event_date_of_a_collected_proclamation(self):
        # The Cook County proclamation is collected, so its override row survives
        # a refresh only through review_decisions.json.
        from _adapter_support import merge_overrides
        reviews = json.loads((BASE / 'review_decisions.json').read_text())
        generated = [dict(declaration_id=k, hazard_category_override=v['hazard_category_override'],
                          review_note=v.get('reason', ''), source_url=v.get('source_url', ''))
                     for k, v in reviews.items() if v.get('hazard_category_override')]
        collected = {r['declaration_id'] for r in self.rows('declarations_for_join.csv')}
        rows, _ = merge_overrides(BASE / 'hazard_overrides.csv', generated, collected)
        kept = {r['declaration_id']: r.get('event_date') for r in rows}
        self.assertEqual(kept.get('IL-PROC-4883F2AF4F255E59'), '2023-09-17')

if __name__ == '__main__':
    unittest.main()
