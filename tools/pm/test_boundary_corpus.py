"""Exercise the manual runner and falsify its verdicts with corrupted observations."""
import copy
import json
import os
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
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertTrue(report['cases'])
            self.assertFalse([r for r in report['cases'] if r['state'] in ('fail', 'incomplete')], report)
            unsupported = [r for r in report['cases'] if r['state'] == 'unsupported']
            self.assertEqual(proc.returncode, 2 if unsupported else 0, proc.stderr)
            self.assertEqual(report['state'], 'incomplete' if unsupported else 'pass')
            self.assertEqual({r['case'] for r in unsupported},
                             {'artifact-absolute_path', 'artifact-json_escape'} if unsupported else set())
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            self.assertIn('ci-job_id/cli.stdout', manifest)
            self.assertFalse(report['external_GET'])

    def test_relative_output_location_runs_the_created_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, '-B', str(Path(corpus.__file__).resolve()),
                                   '--case', 'ci-integer', '--output', 'evidence/run'],
                                  cwd=tmp, capture_output=True, text=True)
            report = json.loads((Path(tmp) / 'evidence/run/results.json').read_text(encoding='utf-8'))
            self.assertEqual(proc.returncode, 0, report)
            self.assertEqual(report['state'], 'pass')
            self.assertEqual(Path(json.loads(proc.stdout)['results']),
                             (Path(tmp) / 'evidence/run/results.json').resolve())

    def test_retention_rejection_stays_a_contract_failure(self):
        for stdout in ['', 'not json', '[]', '{"counts": []}', '{"counts": {}, "jobs": 1}']:
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                script = directory / 'runner.py'
                script.write_text(Path(corpus.__file__).read_text(encoding='utf-8'), encoding='utf-8')
                data = json.loads(Path(corpus.__file__).with_suffix('.json').read_text(encoding='utf-8'))
                data['cases'] = [c for c in data['cases'] if c['id'] == 'ci-late_body']
                script.with_suffix('.json').write_text(json.dumps(data), encoding='utf-8')
                (directory / 'ci_status.py').write_text(
                    'import sys\nsys.stdout.write(' + repr(stdout) + ')\nsys.exit(2)\n', encoding='utf-8')
                output = directory / 'run'
                proc = subprocess.run([sys.executable, '-B', str(script), '--output', str(output)],
                                      capture_output=True, text=True)
                report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertEqual(report['state'], 'fail')
                self.assertTrue(report['cases'][0]['failures'])
                self.assertIn('ci-late_body/cli.stdout',
                              json.loads((output / 'manifest.json').read_text(encoding='utf-8')))

    def test_target_exit_before_gh_keeps_contract_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            script = directory / 'runner.py'
            script.write_text(Path(corpus.__file__).read_text(encoding='utf-8'), encoding='utf-8')
            data = json.loads(Path(corpus.__file__).with_suffix('.json').read_text(encoding='utf-8'))
            data['cases'] = [c for c in data['cases'] if c['id'] == 'pr-normal']
            script.with_suffix('.json').write_text(json.dumps(data), encoding='utf-8')
            (directory / 'pr_file_diff.py').write_text('print("{}"); raise SystemExit(2)', encoding='utf-8')
            output = directory / 'run'
            proc = subprocess.run([sys.executable, '-B', str(script), '--output', str(output)],
                                  capture_output=True, text=True)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertEqual(proc.returncode, 1, report)
            self.assertEqual(report['cases'][0]['state'], 'fail')
            failures = report['cases'][0]['failures']
            self.assertTrue(any('exit:' in item for item in failures), failures)
            self.assertIn('fake gh did not serve all three saved responses', failures)
            self.assertEqual((output / 'pr-normal/cli.stdout').read_text(encoding='utf-8'), '{}\n')

    def test_malformed_generated_manifest_reaches_the_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            script = directory / 'runner.py'
            script.write_text(Path(corpus.__file__).read_text(encoding='utf-8'), encoding='utf-8')
            data = json.loads(Path(corpus.__file__).with_suffix('.json').read_text(encoding='utf-8'))
            data['cases'] = [c for c in data['cases'] if c['id'] == 'artifact-roundtrip']
            script.with_suffix('.json').write_text(json.dumps(data), encoding='utf-8')
            reader = str(Path(corpus.__file__).with_name('artifact_evidence.py'))
            (directory / 'artifact_evidence.py').write_text(
                'import json, pathlib, runpy, sys\n'
                'if sys.argv[1] == "generate":\n'
                '    pathlib.Path(sys.argv[-1]).write_bytes(b"invalid manifest")\n'
                '    print(json.dumps({"generated_files": 4, "evidence": "not_assessed"}))\n'
                'else:\n    runpy.run_path(' + repr(reader) + ', run_name="__main__")\n',
                encoding='utf-8')
            output = directory / 'run'
            proc = subprocess.run([sys.executable, '-B', str(script), '--output', str(output)],
                                  capture_output=True, text=True)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertEqual(proc.returncode, 1, report)
            self.assertEqual(report['cases'][0]['state'], 'fail')
            self.assertTrue(report['cases'][0]['failures'])
            self.assertEqual((output / 'artifact-roundtrip/generated.json').read_bytes(), b'invalid manifest')
            self.assertTrue((output / 'artifact-roundtrip/reader.json').is_file())

    def test_fake_gh_handles_spaces_and_shell_characters_in_python_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "python env ' $fixture"
            parent.mkdir()
            python = parent / 'python'
            python.symlink_to(sys.executable)
            output = Path(tmp) / 'run'
            proc = subprocess.run([str(python), '-B', corpus.__file__, '--case', 'pr-normal',
                                   '--output', str(output)], capture_output=True, text=True)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertEqual(proc.returncode, 0, report)
            self.assertEqual(report['cases'][0]['state'], 'pass')
            calls = (output / 'pr-normal/calls.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(calls), 3)

    def test_long_output_path_never_shifts_the_json_escape_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            if not hasattr(os, 'pathconf') or os.pathconf(tmp, 'PC_PATH_MAX') < 3500:
                self.skipTest('requires a filesystem supporting the long-path fixture')
            directory = Path(tmp)
            while len(str(directory.resolve())) < 322:
                directory = directory / ('base' * 15)
            output = directory / 'run'
            proc = subprocess.run([sys.executable, '-B', corpus.__file__,
                                   '--case', 'artifact-json_escape', '--output', str(output)],
                                  capture_output=True, text=True)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertIn(report['cases'][0]['state'], ('pass', 'unsupported'), report)
            self.assertEqual(proc.returncode, 0 if report['state'] == 'pass' else 2, report)
            if report['cases'][0]['state'] == 'unsupported':
                self.assertIn('JSON byte', report['cases'][0]['error'])

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
            output.write_text('must not exist', encoding='utf-8')
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
            self.assertEqual(json.loads((output / 'results.json').read_text(encoding='utf-8'))['state'], 'incomplete')

    def test_historical_integer_contract_uses_the_target_runtime(self):
        old_source = """import json, pathlib, sys
pathlib.Path('calls.jsonl').touch()
try:
    int('9' * 5000)
except ValueError as exc:
    print('ValueError: ' + str(exc), file=sys.stderr)
else:
    print(json.dumps({'api_consistent': True, 'files': [{'state': 'validated-api-patch'}]}))
sys.exit(1)
"""
        data = json.loads(Path(corpus.__file__).with_suffix('.json').read_text(encoding='utf-8'))
        case = next(c for c in data['cases'] if c['id'] == 'pr-huge_hunk_integer')
        for limit, parent_flags in [('0', []), ('6000', []), ('4300', []),
                                    ('4300', ['-X', 'int_max_str_digits=0'])]:
            with self.subTest(limit=limit, parent_flags=parent_flags), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                source = directory / 'sources' / case['old_sha']
                source.mkdir(parents=True)
                (source / 'pr_file_diff.py').write_text(old_source, encoding='utf-8')
                output = directory / 'run'
                env = dict(os.environ, PYTHONINTMAXSTRDIGITS=limit)
                proc = subprocess.run([sys.executable, '-B', *parent_flags, corpus.__file__,
                                       '--case', case['id'], '--historical-dir',
                                       str(directory / 'sources'), '--output', str(output)],
                                      env=env, capture_output=True, text=True)
                report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
                self.assertEqual(proc.returncode, 0, report)
                self.assertEqual(report['state'], 'pass')

    def test_text_fixtures_are_utf8_under_ascii_locale(self):
        env = dict(os.environ, LC_ALL='C', PYTHONCOERCECLOCALE='0', PYTHONUTF8='0')
        proc = subprocess.run([sys.executable, '-B', '-X', 'utf8=0', '-m', 'unittest',
                               'discover', '-s', str(Path(corpus.__file__).parent),
                               '-p', 'test_boundary_corpus.py', '-k',
                               'test_empty_corpus_and_all_unsupported_cannot_pass'],
                              env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_historical_source_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            proc = subprocess.run([sys.executable, '-B', corpus.__file__, '--case', 'ci-integer',
                                   '--historical-dir', str(Path(tmp) / 'missing'),
                                   '--output', str(output)], capture_output=True)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(report['cases'][0]['state'], 'incomplete')
            self.assertFalse(report['full_corpus'])

    def test_empty_corpus_and_all_unsupported_cannot_pass(self):
        for cases in ([], [{'id': 'unsupported', 'old_sha': 'a' * 40,
                            'target': 'unknown', 'recipe': 'unknown'}]):
            with self.subTest(cases=cases), tempfile.TemporaryDirectory() as tmp:
                script = Path(tmp) / 'runner.py'
                script.write_text(Path(corpus.__file__).read_text(encoding='utf-8'), encoding='utf-8')
                script.with_suffix('.json').write_text(json.dumps({'cases': cases}), encoding='utf-8')
                output = Path(tmp) / 'run'
                proc = subprocess.run([sys.executable, '-B', str(script), '--output', str(output)],
                                      capture_output=True)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertEqual(json.loads((output / 'results.json').read_text(encoding='utf-8'))['state'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
