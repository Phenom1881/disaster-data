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

class ReviewedDecisionTests(unittest.TestCase):
    def test_eo_04_12_is_the_may_2004_severe_weather_declaration(self):
        # "amends Executive Order 04-10 and declares an emergency due to severe
        # weather in all Northern and Central Missouri counties" (June 4, 2004):
        # an amendment by its first words, but the only declaration for the
        # May 2004 storms and flooding (FEMA DR-1524).
        import csv
        here = Path(__file__).resolve().parent
        with (here / 'declarations_for_join.csv').open(encoding='utf-8') as handle:
            joined = {row['declaration_id']: row for row in csv.DictReader(handle)}
        self.assertEqual(joined['MO-EO-04-12']['date_signed'], '2004-06-04')
        with (here / 'mo_order_relationships.csv').open(encoding='utf-8') as handle:
            links = [(r['target_order_id'], r['relationship_type']) for r in csv.DictReader(handle)
                     if r['source_order_id'] == 'MO-EO-04-12']
        self.assertEqual(links, [('MO-EO-04-10', 'amends')])


class LateOrderTests(unittest.TestCase):
    def test_a_refresh_keeps_the_storm_date_of_executive_order_14_12(self):
        import csv
        from _adapter_support import merge_overrides
        here = Path(__file__).parent
        reviews = json.loads((here / 'review_decisions.json').read_text())
        generated = [dict(declaration_id=k, hazard_category_override=v['hazard_category_override'],
                          review_note=v.get('reason', ''), source_url=v.get('source_url', ''))
                     for k, v in reviews.items() if v.get('hazard_category_override')]
        with open(here / 'declarations_for_join.csv', newline='', encoding='utf-8') as handle:
            collected = {r['declaration_id'] for r in csv.DictReader(handle)}
        rows, _ = merge_overrides(here / 'hazard_overrides.csv', generated, collected)
        self.assertEqual({r['declaration_id']: r.get('event_date') for r in rows}.get('MO-EO-14-12'), '2014-09-09')

class CovidEmergencyRowTests(unittest.TestCase):
    """The COVID-19 state of emergency was in force for three storms that have
    no order of their own; each hand row is a match by date only."""

    @staticmethod
    def rows(name):
        import csv
        with (BASE / name).open(newline='', encoding='utf-8') as handle:
            return {row['declaration_id']: row for row in csv.DictReader(handle)}

    def test_each_row_is_dated_by_its_order_register_issue_or_release(self):
        rows, notes = self.rows('manual_declarations.csv'), self.rows('hazard_overrides.csv')
        expected = {
            'MO-SOE-2020-04-24': ('20-09', 'DR-4552', 'https://www.sos.mo.gov/library/reference/orders/2020/eo9'),
            'MO-SOE-2021-06-15': ('21-07', 'DR-4612',
                                  'https://www.sos.mo.gov/CMSImages/AdRules/moreg/2021/v46n12June15/v46n12.pdf'),
            'MO-SOE-2021-12-30': ('21-09', 'DR-4636', 'https://governor.mo.gov/press-releases/archive/'
                                  'governor-parson-announces-covid-19-related-state-emergency-expire-december'),
        }
        self.assertEqual(set(rows), set(expected))
        collected = self.rows('mo_emergency_actions_all.csv')
        for key, (number, fema, url) in expected.items():
            row, note = rows[key], notes[key]
            self.assertEqual(row['declaration_id'], 'MO-SOE-' + row['date_signed'])
            self.assertNotIn(key, collected)
            self.assertEqual((row['governor'], row['eo_number'], row['archive_record_url']),
                             ('Michael L. Parson', number, url), key)
            self.assertIn('matches %s only by date' % fema, row['event_description'])
            self.assertEqual(note['source_url'], url, key)
            self.assertIn('flagged as a date-only match for a different hazard', note['review_note'], key)
        self.assertEqual(collected['MO-EO-20-09']['date_signed'], '2020-04-24')
        self.assertIn("'21-07 Extends Executive Order 20-02", notes['MO-SOE-2021-06-15']['review_note'])
        self.assertIn("until August 31, 2021'", notes['MO-SOE-2021-06-15']['review_note'])
        self.assertIn("'Missouri's COVID-19 related State of Emergency will expire and not be renewed on December "
                      "31, 2021'", notes['MO-SOE-2021-12-30']['review_note'])
        for key in ('MO-SOE-2021-06-15', 'MO-SOE-2021-12-30'):
            self.assertIn('No renewal falls within three weeks of them', notes[key]['review_note'], key)
            self.assertIn('dated by a report', notes[key]['review_note'], key)

    def test_the_coverage_note_says_why_the_three_count(self):
        import subprocess
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
        with tempfile.TemporaryDirectory() as tmp, patch.object(wrapper.subprocess, 'run', return_value=done):
            _, note = wrapper.collect(workdir=tmp, scripts_dir=tmp)
        manifest = json.loads((BASE.parents[1] / 'scripts' / 'plus' / 'state-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(note, next(s['coverage_note'] for s in manifest['states'] if s['abbreviation'] == 'MO'))
        self.assertIn('They count as matched only because the COVID-19 state of emergency (Executive Orders 20-02 '
                      'and 21-09) was in force for each, though it does not name them', note)
        self.assertIn('the Missouri Register of June 15, 2021, which lists its extension to August 31, 2021', note)


if __name__ == '__main__':
    unittest.main()
