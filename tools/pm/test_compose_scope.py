"""Behavior tests through the manual CLI; Python 3.9+."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
EXAMPLES = json.loads((HERE / 'compose_scope_examples.json').read_text())


class ComposeScopeTests(unittest.TestCase):
    def run_cli(self, normal, e2e, code):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for i, data in enumerate([normal, e2e]):
                path = Path(directory) / str(i)
                path.write_text(data if isinstance(data, str) else json.dumps(data))
                paths.append(str(path))
            proc = subprocess.run([sys.executable, str(HERE / 'compose_scope.py')] + paths,
                                  capture_output=True, text=True)
        self.assertEqual(proc.stderr, '')
        self.assertEqual(proc.returncode, code, proc.stdout)
        return json.loads(proc.stdout)

    def test_danger_and_isolated(self):
        result = self.run_cli(EXAMPLES['normal'], EXAMPLES['danger'], 1)
        self.assertEqual({x['kind'] for x in result['findings']},
                         {'project_collision', 'shared_storage'})
        self.assertTrue(result['findings'][1]['e2e_down_v_removal_candidate'])
        self.assertEqual(self.run_cli(EXAMPLES['normal'], EXAMPLES['isolated'], 0)['status'], 'PASS')

    def test_effective_project_overrides_argv(self):
        e2e = copy.deepcopy(EXAMPLES['isolated'])
        e2e['config']['name'] = 'demo'
        result = self.run_cli(EXAMPLES['normal'], e2e, 1)
        self.assertEqual(result['findings'], [{'kind': 'project_collision', 'identity': 'demo'}])
        e2e = copy.deepcopy(EXAMPLES['isolated'])
        e2e['argv'] = EXAMPLES['normal']['argv']
        self.run_cli(EXAMPLES['normal'], e2e, 0)

    def test_explicit_volume_name_crosses_projects(self):
        e2e = copy.deepcopy(EXAMPLES['isolated'])
        e2e['config']['volumes']['data']['name'] = 'demo_data'
        result = self.run_cli(EXAMPLES['normal'], e2e, 1)
        self.assertEqual(result['findings'][0]['kind'], 'shared_storage')
        self.assertTrue(result['findings'][0]['e2e_down_v_removal_candidate'])

    def test_external_and_bind_shared_but_not_deleted(self):
        for kind in ['external', 'bind']:
            normal, e2e = copy.deepcopy(EXAMPLES['normal']), copy.deepcopy(EXAMPLES['isolated'])
            for data in [normal, e2e]:
                if kind == 'external':
                    data['config']['volumes']['data'] = {'name': 'shared', 'external': True}
                else:
                    data['config']['volumes'] = {}
                    data['config']['services']['db']['volumes'] = [
                        {'type': 'bind', 'source': '/tmp/shared', 'target': '/data'}]
            result = self.run_cli(normal, e2e, 1)
            self.assertFalse(result['findings'][0]['e2e_down_v_removal_candidate'])
            self.assertEqual(result['observations'][1]['down_v_named_candidates'], [])

    def test_bad_json_and_required_types(self):
        for data in ['', '{}', '[]', '{"config":{},"config":{}}', '{"a":NaN}',
                     {'argv': [], 'config': {'name': 1, 'services': []}},
                     {'argv': ['docker'], 'compose_version': 1, 'config': []}]:
            with self.subTest(data=data):
                result = self.run_cli(EXAMPLES['normal'], data, 2)
                self.assertTrue(result['unknowns'])
                self.assertEqual(result['observations'][0]['project'], 'demo')

    def test_volumes_from_cannot_pass_as_isolated(self):
        for role in [0, 1]:
            for inherited in [['container:normal-db'], ['db:ro'], None, False, 'db']:
                pair = [copy.deepcopy(EXAMPLES['normal']), copy.deepcopy(EXAMPLES['isolated'])]
                pair[role]['config']['services']['db']['volumes_from'] = inherited
                result = self.run_cli(*pair, 2)
                self.assertTrue(any('volumes_from' in x for x in result['unknowns']))
                self.assertEqual(len(result['observations'][role]['resources']), 1)
        e2e = copy.deepcopy(EXAMPLES['isolated'])
        e2e['config']['services']['db']['volumes_from'] = []
        self.run_cli(EXAMPLES['normal'], e2e, 0)
        e2e = copy.deepcopy(EXAMPLES['danger'])
        e2e['config']['services']['db']['volumes_from'] = ['db']
        result = self.run_cli(EXAMPLES['normal'], e2e, 1)
        self.assertEqual(len(result['findings']), 2)
        self.assertTrue(result['unknowns'])

    def test_bind_directory_overlap_uses_path_components(self):
        for left, right, code in [('/srv/app-data', '/srv/app-data/db', 1),
                                  ('/srv/app-data/db', '/srv/app-data', 1),
                                  ('/srv/app-data', '/srv/app-database', 0),
                                  ('/srv/app-data/a', '/srv/app-data/b', 0),
                                  ('/srv/app-data/', '/srv/app-data/./db', 1),
                                  ('/srv/app-data', '//srv/app-data/db', 1),
                                  ('/srv/app-data/a/..', '/srv/app-data/db', 1),
                                  ('/', '/srv/app-data', 1)]:
            pair = [copy.deepcopy(EXAMPLES['normal']), copy.deepcopy(EXAMPLES['isolated'])]
            for data, source in zip(pair, [left, right]):
                data['config']['volumes'] = {}
                data['config']['services']['db']['volumes'] = [
                    {'type': 'bind', 'source': source, 'target': '/data'}]
            result = self.run_cli(*pair, code)
            if code:
                self.assertEqual(result['findings'][0]['kind'], 'shared_storage')
                self.assertFalse(result['findings'][0]['e2e_down_v_removal_candidate'])
                self.assertEqual(result['observations'][1]['down_v_named_candidates'], [])

    def test_each_required_field_and_missing_file(self):
        for key in ['argv', 'compose_version', 'config']:
            e2e = copy.deepcopy(EXAMPLES['isolated'])
            del e2e[key]
            self.run_cli(EXAMPLES['normal'], e2e, 2)
        e2e = copy.deepcopy(EXAMPLES['isolated'])
        del e2e['config']['name']
        self.run_cli(EXAMPLES['normal'], e2e, 2)
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / 'absent')
            proc = subprocess.run([sys.executable, str(HERE / 'compose_scope.py'), missing, missing],
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(len(json.loads(proc.stdout)['unknowns']), 2)

    def test_partial_error_retains_danger_and_good_observations(self):
        e2e = copy.deepcopy(EXAMPLES['danger'])
        e2e['config']['services']['bad'] = {'volumes': [False]}
        result = self.run_cli(EXAMPLES['normal'], e2e, 1)
        self.assertTrue(result['unknowns'])
        self.assertEqual(len(result['findings']), 2)
        self.assertEqual(result['observations'][1]['down_v_named_candidates'], ['demo_data'])

    def test_unknown_mounts_and_volume_definitions(self):
        for replacement in [None, [], {'data': None}, {'data': {'name': ''}},
                            {'data': {'name': 'demo_e2e_data', 'external': 'false'}},
                            {'data': {'name': 'demo_e2e_data', 'driver': 'remote'}}]:
            e2e = copy.deepcopy(EXAMPLES['isolated'])
            e2e['config']['volumes'] = replacement
            self.run_cli(EXAMPLES['normal'], e2e, 2)
        for mount in [{'type': 'volume', 'target': '/anon'},
                      {'type': 'future', 'target': '/x'}, 'data:/x',
                      {'type': 'bind', 'source': './relative', 'target': '/x'}]:
            e2e = copy.deepcopy(EXAMPLES['isolated'])
            e2e['config']['services']['db']['volumes'] = [mount]
            self.run_cli(EXAMPLES['normal'], e2e, 2)


if __name__ == '__main__':
    unittest.main()
