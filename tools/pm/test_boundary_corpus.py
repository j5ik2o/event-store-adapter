"""Exercise the manual runner and falsify its verdicts with corrupted observations."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import boundary_corpus as corpus


class CorpusTests(unittest.TestCase):
    def test_all_local_cli_contracts_and_unsupported_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            proc = subprocess.run([sys.executable, '-B', str(Path(corpus.__file__)),
                                   '--output', str(output)], capture_output=True, text=True)
            report = json.loads((output / 'results.json').read_text())
            self.assertTrue(report['cases'])
            self.assertFalse([r for r in report['cases'] if r['state'] in ('fail', 'incomplete')], report)
            unsupported = [r for r in report['cases'] if r['state'] == 'unsupported']
            self.assertEqual(proc.returncode, 2 if unsupported else 0, proc.stderr)
            self.assertEqual(report['state'], 'incomplete' if unsupported else 'pass')
            self.assertEqual({r['case'] for r in unsupported},
                             {'artifact-absolute_path', 'artifact-json_escape'} if unsupported else set())
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertIn('ci-job_id/cli.stdout', manifest)
            self.assertFalse(report['external_GET'])

    def test_rejection_exit_two_is_a_pass_only_with_the_full_contract(self):
        expected = {'exit': 2, 'fields': {'execution/state': 'unknown',
                    'execution/observed_failure': True}, 'stderr': 'nonempty', 'output': False,
                    'errors': True}
        result = {'exit': 2, 'stdout': json.dumps({'execution': {'state': 'unknown',
                  'observed_failure': True}, 'acquisition_errors': [{'reason': 'bad'}]}),
                  'stderr': 'diagnostic\n'}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'absent'
            self.assertEqual(corpus.check(result, expected, output), [])
            for key, value in [('exit', 0), ('stdout', '{}'), ('stderr', ''),
                               ('stdout', 'not json'), ('stderr', 'Traceback')]:
                broken = dict(result, **{key: value})
                self.assertTrue(corpus.check(broken, expected, output), broken)
            output.write_text('must not exist')
            self.assertTrue(corpus.check(result, expected, output))

    def test_known_failure_requires_raw_evidence_and_counts(self):
        fixture = {'responses': {'x': {'body': {'jobs': [{'id': 4, 'conclusion': 'failure'}]}}}}
        report = {k: [] for k in ('check_runs', 'suites', 'workflow_runs', 'jobs', 'commit_statuses')}
        report['jobs'] = [{'id': 4, 'conclusion': 'failure'}]
        report['counts'] = {k: len(v) for k, v in report.items()}
        self.assertEqual(corpus.retention({'stdout': json.dumps(report)}, fixture), [])
        for mutation in ('drop', 'change', 'count', 'bool_count'):
            broken = copy.deepcopy(report)
            if mutation == 'drop':
                broken['jobs'] = []
            elif mutation == 'change':
                broken['jobs'][0]['conclusion'] = 'success'
            elif mutation == 'bool_count':
                broken['counts']['jobs'] = True
            else:
                broken['counts']['jobs'] = 0
            self.assertTrue(corpus.retention({'stdout': json.dumps(broken)}, fixture))

    def test_unknown_case_never_reports_zero_case_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            proc = subprocess.run([sys.executable, '-B', corpus.__file__, '--case', 'does-not-exist',
                                   '--output', str(output)], capture_output=True)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads((output / 'results.json').read_text())['state'], 'incomplete')

    def test_missing_historical_source_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            proc = subprocess.run([sys.executable, '-B', corpus.__file__, '--case', 'ci-integer',
                                   '--historical-dir', str(Path(tmp) / 'missing'),
                                   '--output', str(output)], capture_output=True)
            report = json.loads((output / 'results.json').read_text())
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(report['cases'][0]['state'], 'incomplete')
            self.assertFalse(report['full_corpus'])

    def test_empty_corpus_and_all_unsupported_cannot_pass(self):
        for cases in ([], [{'id': 'unsupported', 'old_sha': 'a' * 40,
                            'target': 'unknown', 'recipe': 'unknown'}]):
            with self.subTest(cases=cases), tempfile.TemporaryDirectory() as tmp:
                script = Path(tmp) / 'runner.py'
                script.write_text(Path(corpus.__file__).read_text())
                script.with_suffix('.json').write_text(json.dumps({'cases': cases}))
                output = Path(tmp) / 'run'
                proc = subprocess.run([sys.executable, '-B', str(script), '--output', str(output)],
                                      capture_output=True)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertEqual(json.loads((output / 'results.json').read_text())['state'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
