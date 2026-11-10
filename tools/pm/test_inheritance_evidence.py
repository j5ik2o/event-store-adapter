"""Exercise the public CLI with byte-bound records and rejection contrasts."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from inheritance_example import create, save

CLI = Path(__file__).with_name('inheritance_evidence.py')


class InheritanceCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'with spaces'
        self.data = create(self.root)

    def invoke(self, code=0):
        save(self.root, 'input.json', self.data)
        result = subprocess.run([sys.executable, '-B', str(CLI), str(self.root / 'input.json')],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def old(self, **changes):
        run = json.loads((self.root / 'old.json').read_text())
        run.update(changes)
        self.data['prior_runs'] = [save(self.root, 'old.json', run)]

    def test_limited_inheritance_is_not_new_execution(self):
        out = self.invoke()
        self.assertTrue(out['all_requirements_accounted'])
        self.assertFalse(out['current_execution_complete'])
        self.assertEqual(out['recorded_new_runs'], [])
        self.assertEqual(out['inherited_runs'], ['old-1'])
        self.assertEqual(out['requirements'][0]['state'], 'inherited')

    def test_new_suite_not_double_counted_and_gaps_remain(self):
        run = json.loads((self.root / 'old.json').read_text())
        run.update(run_id='new-1', head=self.data['head'])
        run['conditions'] = dict(run['conditions'], suite='new selected tests')
        run['evidence'] = [save(self.root, 'new-proof.txt', b'new synthetic observation')]
        self.data['new_runs'] = [save(self.root, 'new.json', run)]
        self.data['requirements'].append(dict(self.data['requirements'][0], id='tests', conditions=run['conditions']))
        out = self.invoke()
        self.assertEqual(out['recorded_new_runs'], ['new-1'])
        self.assertEqual(out['inherited_runs'], ['old-1'])
        self.data['requirements'].append(dict(self.data['requirements'][0], id='linux', conditions=dict(run['conditions'], runtime='Linux')))
        out = self.invoke(1)
        self.assertEqual(out['unverified'], ['linux'])
        self.assertEqual(out['requirements'][2]['state'], 'unverified')

    def test_fail_unknown_not_run_and_gaps_never_promoted(self):
        for verdict in ('fail', 'unknown', 'not_run'):
            self.old(verdict=verdict)
            out = self.invoke(1)
            self.assertIn('original_verdict_' + verdict, out['requirements'][0]['rejected'][0]['reasons'])
            self.assertEqual(out['unverified'], ['source'])
        self.old(verdict='pass', unverified=['not checked'])
        self.assertIn('run_has_unverified', self.invoke(1)['requirements'][0]['rejected'][0]['reasons'])

    def test_changed_and_null_conditions(self):
        original = copy.deepcopy(self.data)
        for field in ('runtime', 'command', 'suite'):
            for value in ('changed', None):
                self.data = copy.deepcopy(original)
                self.data['requirements'][0]['conditions'][field] = value
                out = self.invoke(1)
                self.assertIn('conditions_changed', out['requirements'][0]['rejected'][0]['reasons'])
        cond = dict(original['requirements'][0]['conditions'], runtime=None)
        self.old(conditions=cond)
        self.data['requirements'][0]['conditions'] = cond
        self.assertIn('unknown_conditions', self.invoke(1)['requirements'][0]['rejected'][0]['reasons'])

    def test_changed_target_and_base(self):
        target = dict(save(self.root, 'changed.txt', b'changed source'), name='source')
        self.data['requirements'][0]['targets'] = [target]
        self.assertIn('targets_changed', self.invoke(1)['requirements'][0]['rejected'][0]['reasons'])
        self.old(base='3' * 40)
        self.assertIn('base_changed', self.invoke(1)['requirements'][0]['rejected'][0]['reasons'])

    def test_hash_mismatch_missing_and_partial_observations(self):
        self.data['new_runs'] = [{'path': 'missing.json', 'sha256': '0' * 64}]
        out = self.invoke(2)
        self.assertEqual(len(out['observations']), 1)
        self.assertFalse(out['inspection_complete'])
        self.assertTrue(out['errors'])
        self.assertTrue(any(f['path'].endswith('old-proof.txt') for f in out['verified_files']))
        self.data['new_runs'] = []
        (self.root / 'old-proof.txt').write_text('tampered')
        self.assertIn('hash mismatch', self.invoke(2)['errors'][0])

    def test_duplicate_identity_and_relabelled_old_evidence(self):
        old = self.data['prior_runs'][0]
        self.data['prior_runs'].append(old)
        self.assertIn('duplicate run identity', self.invoke(2)['errors'][0])
        self.data['prior_runs'].pop()
        run = json.loads((self.root / 'old.json').read_text())
        run.update(run_id='renamed', head=self.data['head'])
        self.data['new_runs'] = [save(self.root, 'new.json', run)]
        self.assertIn('reused run evidence', self.invoke(2)['errors'][0])

    def test_missing_evidence_and_url_not_a_local_artifact(self):
        self.old(evidence=[])
        self.invoke(2)
        self.old(evidence=[{'path': 'https://example.org/report', 'sha256': '0' * 64}])
        self.assertIn('missing or nonregular', self.invoke(2)['errors'][0])

    def test_run_schema_enums_bool_null_and_fields(self):
        original = json.loads((self.root / 'old.json').read_text())
        for changes in ({'schema_version': True}, {'schema_version': None}, {'verdict': []},
                        {'verdict': 'PASS'}, {'run_id': None}, {'provenance': None},
                        {'conditions': []}, {'evidence': None}, {'extra': 1}):
            save(self.root, 'old.json', original)
            self.old(**changes)
            self.invoke(2)
        save(self.root, 'old.json', original)
        self.old()
        self.data['schema_version'] = True
        self.invoke(2)

    def test_duplicate_json_keys_and_unreadable_json(self):
        run = json.loads((self.root / 'old.json').read_text(encoding='utf-8'))
        duplicate = json.dumps(run).replace('"verdict": "pass"',
                                            '"verdict": "pass", "verdict": "pass"')
        self.data['prior_runs'] = [save(self.root, 'old.json', duplicate.encode('utf-8'))]
        self.assertIn('duplicate JSON key: verdict', self.invoke(2)['errors'][0])
        for raw in (b'{"schema_version":1,"schema_version":1}', b'null', b'\xff', b'[' * 2000):
            self.data['prior_runs'] = [save(self.root, 'old.json', raw)]
            self.invoke(2)

    def test_links_targets_and_new_revision(self):
        link = self.data['inherited'][0]
        self.data['inherited'].append(link)
        self.invoke(2)
        self.data['inherited'] = [dict(link, run_id='absent')]
        self.invoke(2)
        self.data['inherited'] = []
        self.data['new_runs'] = self.data['prior_runs']
        self.data['prior_runs'] = []
        self.assertIn('revision mismatch', self.invoke(2)['errors'][0])

    def test_new_run_can_cover_multiple_requirements_once(self):
        run = json.loads((self.root / 'old.json').read_text())
        run.update(head=self.data['head'])
        self.data['new_runs'] = [save(self.root, 'new.json', run)]
        self.data.update(prior_runs=[], inherited=[])
        self.data['requirements'].append(dict(self.data['requirements'][0], id='second'))
        out = self.invoke()
        self.assertTrue(out['current_execution_complete'])
        self.assertEqual(out['recorded_new_runs'], ['old-1'])

    def test_rejected_inheritance_is_not_hidden_by_new_pass(self):
        run = json.loads((self.root / 'old.json').read_text())
        run.update(run_id='new-1', head=self.data['head'])
        run['evidence'] = [save(self.root, 'new-proof.txt', b'distinct new evidence')]
        self.data['new_runs'] = [save(self.root, 'new.json', run)]
        self.old(verdict='fail')
        out = self.invoke(1)
        self.assertEqual(out['requirements'][0]['state'], 'new')
        self.assertFalse(out['all_requirements_accounted'])
        self.assertEqual(out['recorded_new_runs'], ['new-1'])
        self.assertIn('original_verdict_fail', out['requirements'][0]['rejected'][0]['reasons'])

    def test_requirement_and_target_omissions_are_not_covered(self):
        requirement = copy.deepcopy(self.data['requirements'][0])
        requirement['targets'].append(dict(save(self.root, 'other.txt', b'other'), name='other'))
        self.data['requirements'] = [requirement]
        self.assertIn('targets_changed', self.invoke(1)['requirements'][0]['rejected'][0]['reasons'])
        self.data['requirements'] = []
        self.invoke(2)

    def test_bounded_input_and_no_command_execution(self):
        self.data['prior_runs'] = [save(self.root, 'large.json', b' ' * (1024 * 1024 + 1))]
        self.assertIn('exceeds', self.invoke(2)['errors'][0])
        self.data = create(self.root / 'other')
        self.root /= 'other'
        command = 'touch ' + str(self.root / 'marker')
        self.old(conditions=dict(self.data['requirements'][0]['conditions'], command=command))
        self.data['requirements'][0]['conditions']['command'] = command
        self.invoke()
        self.assertFalse((self.root / 'marker').exists())


if __name__ == '__main__':
    unittest.main()
