import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).with_name('verification_conditions.py')
EXAMPLE = CLI.with_name('verification_conditions_java814.json')


def fixture():
    condition = dict(repository='example/repo', revision='a' * 40, base='b' * 40,
                     jdk='17.0.21', runtime='Gradle 9 on Linux x86_64',
                     command='./gradlew test', suite='full',
                     resources=dict(heap='512MiB', cpu='2 cores', memory='4GiB', parallelism='1 worker'))
    run = dict(id='author', actor='implementation-session', role='author', conditions=condition,
               result='pass', evidence=['https://example.org/log'], unverified=[])
    review = copy.deepcopy(run)
    review.update(id='review', actor='review-session', role='review')
    return dict(schema_version=1, requirements=[dict(id='full17', conditions=condition)], runs=[run, review])


class ComparisonTest(unittest.TestCase):
    def invoke(self, data, raw=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text(data if raw else json.dumps(data), encoding='utf-8')
            result = subprocess.run([sys.executable, str(CLI), str(path)], capture_output=True, text=True)
        self.assertEqual(result.stderr, '')
        return result.returncode, json.loads(result.stdout)

    def test_repeat_is_overlap_not_expansion_and_can_complete(self):
        code, out = self.invoke(fixture())
        self.assertEqual(code, 0)
        self.assertTrue(out['complete'])
        self.assertEqual(out['overlap'], [{'review': 'review', 'authors': ['author']}])
        self.assertEqual(out['added_review_conditions'], [])
        self.assertEqual(out['requirements'][0]['review'], ['review'])
        self.assertFalse(out['evidence_verified'])
        self.assertFalse(out['independence_verified'])

    def test_added_jdk_covers_only_explicit_requirement(self):
        data = fixture()
        data['runs'][1]['conditions']['jdk'] = '19'
        data['requirements'].append(dict(id='full19', conditions=copy.deepcopy(data['runs'][1]['conditions'])))
        code, out = self.invoke(data)
        self.assertEqual(code, 0)
        self.assertEqual(out['added_review_conditions'], ['review'])
        self.assertEqual(out['requirements'][0]['review'], [])
        self.assertEqual(out['requirements'][1]['review'], ['review'])

    def test_condition_changes_do_not_inherit_pass(self):
        for field, value in [('revision', 'c' * 40), ('base', 'c' * 40), ('jdk', '19'),
                             ('suite', 'conformance'), ('command', './gradlew test --info'),
                             ('runtime', 'different OS')]:
            with self.subTest(field=field):
                data = fixture()
                data['requirements'][0]['conditions'] = copy.deepcopy(data['requirements'][0]['conditions'])
                data['requirements'][0]['conditions'][field] = value
                code, out = self.invoke(data)
                self.assertEqual(code, 1)
                self.assertEqual(out['unverified'], ['full17'])
                self.assertEqual(out['requirements'][0]['reasons'][0]['code'], 'no_exact_run')

    def test_unknown_conditions_never_cover_even_when_equal(self):
        for field in ['revision', 'base', 'runtime', 'command', 'heap', 'cpu', 'memory', 'parallelism']:
            data = fixture()
            for record in data['runs'] + data['requirements']:
                container = record['conditions'] if field not in ['heap', 'cpu', 'memory', 'parallelism'] else record['conditions']['resources']
                container[field] = None
            code, out = self.invoke(data)
            self.assertEqual(code, 1)
            self.assertFalse(out['runs'][0]['eligible_pass'])
            self.assertIn('unknown_condition', [r['code'] for r in out['runs'][0]['reasons']])

    def test_nonpass_missing_evidence_and_unverified_reject_pass(self):
        for field, value, reason in [('result', 'fail', 'result_fail'), ('result', 'unknown', 'result_unknown'),
                                     ('result', 'not_run', 'result_not_run'), ('evidence', [], 'missing_evidence'),
                                     ('unverified', ['suite not run'], 'declared_unverified')]:
            data = fixture()
            for run in data['runs']:
                run[field] = value
            code, out = self.invoke(data)
            self.assertEqual(code, 1)
            self.assertIn(reason, [r['code'] for r in out['runs'][0]['reasons']])

    def test_invalid_input_is_machine_readable(self):
        for data in ['', '{}', '[]', '{', '{"schema_version":1,"schema_version":1}',
                     json.dumps(dict(schema_version=1, requirements=[], runs=[]))]:
            with self.subTest(data=data):
                code, out = self.invoke(data, raw=True)
                self.assertEqual(code, 2)
                self.assertFalse(out['complete'])
                self.assertTrue(out['errors'][0]['code'])
        for mutate in [lambda d: d['runs'][0].pop('actor'),
                       lambda d: d['runs'][0]['conditions']['resources'].pop('heap'),
                       lambda d: d['runs'][0].update(result='PASS'),
                       lambda d: d['runs'][0]['conditions'].update(revision='main'),
                       lambda d: d['runs'][0]['conditions']['resources'].update(heap='unknown'),
                       lambda d: d['runs'].append(copy.deepcopy(d['runs'][0]))]:
            data = fixture()
            mutate(data)
            self.assertEqual(self.invoke(data)[0], 2)

    def test_command_text_is_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'executed'
            data = fixture()
            for run in data['runs']:
                run['conditions']['command'] = f'touch {marker}'
            self.invoke(data)
            self.assertFalse(marker.exists())

    def test_duplicate_key_in_valid_document_is_rejected(self):
        raw = json.dumps(fixture())
        duplicate = raw.replace('"heap": "512MiB"',
                                '"heap": "512MiB", "heap": "512MiB"', 1)
        self.assertNotEqual(raw, duplicate)
        code, out = self.invoke(duplicate, raw=True)
        self.assertEqual(code, 2)
        self.assertFalse(out['complete'])
        self.assertEqual(out['errors'], [{'code': 'duplicate_json_key', 'path': 'heap'}])

    def test_sourced_java_example(self):
        code, out = self.invoke(json.loads(EXAMPLE.read_text()))
        self.assertEqual(code, 1)
        self.assertFalse(out['complete'])
        self.assertEqual(out['scope_overlap'][0]['author'], 'java-author-jdk11')
        self.assertEqual(out['scope_overlap'][0]['review'], 'java-review-jdk11')
        self.assertIn('command', out['scope_overlap'][0]['different_fields'])
        self.assertIn('old-head-jdk17-full', out['unverified'])
        self.assertEqual(out['requirements'][1]['review'], [])
        self.assertIn('java-review-fixed-jdk17', out['added_review_conditions'])


if __name__ == '__main__':
    unittest.main()
