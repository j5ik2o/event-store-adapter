"""Behavior controls through the public CLI. Never creates a git repository."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
CLI = HERE / "delegation_preflight.py"
EXAMPLES = HERE / "delegation_preflight_examples.json"
BASE = json.loads(EXAMPLES.read_text())["cases"]["common-alias"]["input"]


class PreflightTests(unittest.TestCase):
    def run_cli(self, data, *args):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run([sys.executable, str(CLI), str(source), *args],
                                    capture_output=True, text=True)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        return result, report

    def test_self_contained_cases(self):
        cases = json.loads(EXAMPLES.read_text())["cases"]
        self.assertGreaterEqual(len(cases), 5)
        for name, case in cases.items():
            with self.subTest(case=name):
                run = subprocess.run([sys.executable, str(CLI), str(EXAMPLES), "--case", name],
                                     capture_output=True, text=True)
                report = json.loads(run.stdout)
                self.assertEqual(run.returncode, case["expected"]["exit"])
                self.assertEqual(report["plan"], case["expected"]["plan"])
                self.assertEqual(report["checkout"], case["expected"]["checkout"])
                self.assertEqual(run.stderr, "")
                self.assertEqual(report["mode"], "snapshot")

    def test_missing_scope_and_source_never_allow(self):
        for scope in ({}, {**BASE['scope'], 'source':None},
                      {**BASE['scope'], 'policy':'future_policy'}):
            data = copy.deepcopy(BASE)
            data['scope'] = scope
            run, report = self.run_cli(data)
            self.assertEqual(run.returncode, 1)
            self.assertIn(report['plan'], ('unknown', 'incomplete'))
            self.assertEqual(report['checkout'], 'snapshot_match')

    def test_drift_and_partial_failure_preserve_observations(self):
        for field in ('root', 'head', 'branch', 'status', 'origin'):
            data = copy.deepcopy(BASE)
            data['snapshot'][field] = {'value':'changed'}
            run, report = self.run_cli(data)
            self.assertEqual(run.returncode, 1)
            self.assertEqual(report['checkout'], 'mismatch')
            self.assertIn('checkout_'+field, report['reasons'])
        for entry in (None, {'error':'failed with https://secret:password@host/repo'}):
            data = copy.deepcopy(BASE)
            if entry is None:
                del data['snapshot']['branch']
            else:
                data['snapshot']['branch'] = entry
            run, report = self.run_cli(data)
            self.assertEqual(run.returncode, 1)
            self.assertEqual(report['checkout'], 'incomplete')
            self.assertEqual(report['observations']['head']['value'], 'a'*40)
            self.assertNotIn('password', run.stdout + run.stderr)

    def test_explicit_alias_only_and_credentials_redacted(self):
        for origin, aliases, code in (
            ('https://user:password@github.com/j5ik2o/event-store-adapter.git', {}, 0),
            ('ssh://git@j5ik2o.github.com/j5ik2o/event-store-adapter.git', {}, 1),
            ('https://another-forge.test/j5ik2o/event-store-adapter.git', BASE['host_aliases'], 1)):
            data = copy.deepcopy(BASE)
            data['snapshot']['origin']['value'] = origin
            data['host_aliases'] = aliases
            run, report = self.run_cli(data)
            self.assertEqual(run.returncode, code)
            self.assertNotIn('password', run.stdout + run.stderr)
            self.assertNotIn('user:', run.stdout + run.stderr)

    def test_malformed_external_types(self):
        variants = [None, [], {**BASE,'schema_version':True}, {**BASE,'schema_version':1.0},
                    {**BASE,'requested':None},
                    {**BASE,'requested':{'repo':BASE['requested']['repo'], 'project_id':'common'}}, {**BASE,'assignment':False},
                    {**BASE,'snapshot':{'head':{'value':None}}},
                    {**BASE,'scope':{'policy':True}}, {**BASE,'host_aliases':{'x':1}},
                    {**BASE,'assignment':{**BASE['assignment'],'status':None}},
                    {**BASE,'command':'touch /tmp/never-execute-preflight'}]
        for data in variants:
            with self.subTest(data=data):
                run, report = self.run_cli(data)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(report['comparison'], 'invalid_input')
                self.assertTrue(run.stderr)

    def test_absent_live_path_retains_each_failure(self):
        data = copy.deepcopy(BASE)
        data['assignment']['path'] = '/nonexistent-preflight-checkout/control'
        run, report = self.run_cli(data, '--checkout', data['assignment']['path'])
        self.assertEqual(run.returncode, 1)
        self.assertEqual(report['checkout'], 'incomplete')
        self.assertEqual(set(report['observations']), {'root','origin','head','branch','status'})
        self.assertTrue(all('error' in entry for entry in report['observations'].values()))

    def test_wrong_live_path_and_unassigned_are_not_observed(self):
        for assigned in (BASE['assignment'], None):
            data = copy.deepcopy(BASE)
            data['assignment'] = assigned
            run, report = self.run_cli(data, '--checkout', str(HERE))
            self.assertEqual(run.returncode, 1)
            self.assertEqual(report['observations'], {})
            self.assertIn(report['checkout'], ('mismatch','not_observed'))

    def test_environment_scope_requires_matching_environment(self):
        data = copy.deepcopy(BASE)
        data['scope'].update(policy='environment_project', environment_id='linked-environment')
        run, report = self.run_cli(data)
        self.assertEqual(report['plan'], 'rejected')
        data['requested']['environment_id'] = 'linked-environment'
        run, report = self.run_cli(data)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(report['plan'], 'compatible')
        data['scope']['environment_id'] = None
        run, report = self.run_cli(data)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(report['plan'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
