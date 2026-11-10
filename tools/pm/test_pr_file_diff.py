import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('pr_file_diff.py')
META = {'head': {'sha': 'a' * 40}, 'base': {'sha': 'b' * 40},
        'changed_files': 1, 'additions': 1, 'deletions': 1}
FILE = {'filename': 'fixture.txt', 'status': 'modified', 'sha': 'c' * 40,
        'additions': 1, 'deletions': 1, 'changes': 2,
        'patch': '@@ -1 +1 @@\n-old\n+new'}


class PrFileDiffTest(unittest.TestCase):
    def invoke(self, responses, names=('fixture.txt',), extra=(), url=False, target=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'responses.json').write_text(json.dumps(responses))
            gh = root / 'gh'
            gh.write_text('''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
root = Path(__file__).parent
calls = root / 'calls.jsonl'
index = len(calls.read_text().splitlines()) if calls.exists() else 0
with calls.open('a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
responses = json.loads((root / 'responses.json').read_text())
if index >= len(responses):
    print(os.environ['PM_DIFF_TEST_LEAK_SENTINEL'])
    print(os.environ['PM_DIFF_TEST_LEAK_SENTINEL'], file=sys.stderr)
    raise SystemExit(7)
print(json.dumps(responses[index]))
''')
            gh.chmod(0o755)
            arguments = ['https://github.com/owner/repo/pull/12'] if url else ['owner/repo', '12']
            if target is not None:
                arguments = list(target)
            for name in names:
                arguments += ['--file', name]
            result = subprocess.run([sys.executable, str(SCRIPT), *arguments, *extra],
                                    env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                                             PM_DIFF_TEST_LEAK_SENTINEL='LEAK_SENTINEL'),
                                    capture_output=True, text=True, cwd=root)
            calls = root / 'calls.jsonl'
            history = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            self.assertEqual(result.stderr, '')
            self.assertFalse((root / 'EXECUTED').exists())
            return result.returncode, json.loads(result.stdout), history, len(result.stdout.encode())

    def test_normal_exact_selection_and_url(self):
        code, report, calls, _ = self.invoke([META, [FILE], META], url=True)
        self.assertEqual(code, 1)
        self.assertTrue(report['api_consistent'])
        self.assertFalse(report['complete'])
        self.assertEqual(report['reasons'], ['api_only_completeness_unproven'])
        self.assertEqual(report['files'][0]['patch'], FILE['patch'])
        self.assertEqual(report['revision']['before'], report['revision']['after'])
        self.assertIn('API consistency', report['limitations'][0])
        self.assertTrue(all(call[:6] == ['api', '--hostname', 'github.com', '--method', 'GET', '-H'] for call in calls))

    def test_pagination_reaches_selected_file_after_first_page(self):
        first = [dict(FILE, filename=f'file{i}') for i in range(100)]
        meta = dict(META, changed_files=101, additions=101, deletions=101)
        code, report, calls, _ = self.invoke([meta, first, [FILE], meta])
        self.assertEqual(code, 1)
        self.assertTrue(report['api_consistent'])
        self.assertEqual(report['files_received'], 101)
        self.assertEqual(report['unselected']['count'], 100)
        self.assertTrue(calls[2][-1].endswith('per_page=100&page=2'))

    def test_missing_truncated_and_omitted_hunks(self):
        for patch in (None, '', '@@ -1 +1 @@\n-old', '+new',
                      '@@ -1 +1 @@\n-old\n+new\n...',
                      '@@ -1 +1 @@\n-old\n+new'):
            with self.subTest(patch=patch):
                item = dict(FILE, patch=patch)
                meta = META
                if patch == FILE['patch']:
                    item.update(additions=2, changes=3)
                    meta = dict(META, additions=2)
                code, report, _, _ = self.invoke([meta, [item], meta])
                self.assertEqual(code, 1)
                self.assertFalse(report['complete'])
                self.assertIsNone(report['files'][0]['patch'])
                self.assertTrue(report['files'][0]['reasons'])

    def test_revision_change_in_head_or_base(self):
        for side in ('head', 'base'):
            after = dict(META, **{side: {'sha': 'd' * 40}})
            code, report, _, _ = self.invoke([META, [FILE], after])
            self.assertEqual(code, 1)
            self.assertIn('revision_or_metadata_changed', report['reasons'])

    def test_no_newline_marker_rejects_invalid_positions(self):
        marker = '\\ No newline at end of file'
        cases = [
            (f'@@ -1 +1 @@\n{marker}\n-old\n+new', 1, 1),
            (f'@@ -1 +1 @@\n-old\n{marker}\n{marker}\n+new', 1, 1),
            (f'@@ -1,2 +1 @@\n-old\n{marker}\n-other\n+new', 1, 2),
            (f'@@ -1 +1 @@\n-old\n{marker}\n+new\n@@ -3 +3 @@\n-a\n+b', 2, 2),
        ]
        for patch, additions, deletions in cases:
            with self.subTest(patch=patch):
                item = dict(FILE, patch=patch, additions=additions, deletions=deletions,
                            changes=additions + deletions)
                meta = dict(META, additions=additions, deletions=deletions)
                code, report, _, _ = self.invoke([meta, [item], meta])
                self.assertEqual(code, 1)
                self.assertFalse(report['api_consistent'])
                self.assertIsNone(report['files'][0]['patch'])
                self.assertIn('newline_marker_invalid', report['files'][0]['reasons'])

    def test_no_newline_marker_accepts_final_old_new_and_context_lines(self):
        marker = '\\ No newline at end of file'
        patches = [f'@@ -1 +1 @@\n-old\n{marker}\n+new',
                   f'@@ -1 +1 @@\n-old\n+new\n{marker}',
                   f'@@ -1 +1 @@\n-old\n{marker}\n+new\n{marker}',
                   f'@@ -1,2 +1,2 @@\n-old\n+new\n last\n{marker}']
        for patch in patches:
            with self.subTest(patch=patch):
                _, report, _, _ = self.invoke([META, [dict(FILE, patch=patch)], META])
                self.assertTrue(report['api_consistent'])
                self.assertEqual(report['files'][0]['patch'], patch)

    def test_hunk_numbers_are_bounded_without_losing_json_response(self):
        for index in range(4):
            fields = ['1', '1', '1', '1']
            fields[index] = '9' * 5000
            patch = f'@@ -{fields[0]},{fields[1]} +{fields[2]},{fields[3]} @@\n-old\n+new'
            with self.subTest(field=index):
                code, report, _, _ = self.invoke([META, [dict(FILE, patch=patch)], META])
                self.assertEqual(code, 1)
                self.assertFalse(report['api_consistent'])
                self.assertIsNone(report['files'][0]['patch'])
                self.assertIn('hunk_number_out_of_range', report['files'][0]['reasons'])

    def test_missing_selection_is_not_empty_diff(self):
        code, report, _, _ = self.invoke([META, [FILE], META], names=('absent',))
        self.assertEqual(code, 1)
        self.assertEqual(report['files'][0]['reasons'], ['selected_path_missing'])
        self.assertIsNone(report['files'][0]['patch'])

    def test_binary_unknown_and_rename_only_are_distinct(self):
        for status, reason in [('modified', 'zero_text_changes_binary_or_metadata'), ('renamed', 'rename_only')]:
            item = dict(FILE, status=status, additions=0, deletions=0, changes=0, patch=None)
            meta = dict(META, additions=0, deletions=0)
            code, report, _, _ = self.invoke([meta, [item], meta])
            self.assertEqual(code, 1)
            self.assertEqual(report['files'][0]['state'], 'metadata-only')
            self.assertEqual(report['files'][0]['reasons'], [reason])

    def test_short_page_duplicate_counts_and_cap_fail_closed(self):
        cases = [(dict(META, changed_files=2), [FILE], 'file_count_mismatch'),
                 (META, [FILE, FILE], 'duplicate_filename'),
                 (dict(META, changed_files=3001), [FILE], 'github_files_limit'),
                 (dict(META, additions=2), [FILE], 'additions_total_mismatch')]
        for meta, files, reason in cases:
            code, report, _, _ = self.invoke([meta, files, meta])
            self.assertEqual(code, 1)
            self.assertIn(reason, report['reasons'])

    def test_full_thirty_pages_stop_at_github_ceiling(self):
        pages = [[dict(FILE, filename=f'file{page * 100 + index}')
                  for index in range(100)] for page in range(30)]
        meta = dict(META, changed_files=3000, additions=3000, deletions=3000)
        code, report, calls, _ = self.invoke([meta, *pages, meta], names=('file2999',))
        self.assertEqual(code, 1)
        self.assertEqual(report['files_received'], 3000)
        self.assertEqual(len(calls), 32)
        self.assertIn('github_files_limit', report['reasons'])

    def test_failure_during_pagination_preserves_incomplete_revision(self):
        first = [dict(FILE, filename=f'file{i}') for i in range(100)]
        meta = dict(META, changed_files=101, additions=101, deletions=101)
        code, report, _, _ = self.invoke([meta, first])
        self.assertEqual(code, 1)
        self.assertFalse(report['complete'])
        self.assertIn('before', report['revision'])
        self.assertNotIn('after', report['revision'])
        self.assertEqual(report['reasons'], ['api_request_failed'])

    def test_path_is_data_and_never_passed_to_gh(self):
        name = 'odd\n$(touch EXECUTED);`touch EXECUTED` * [x].txt'
        code, report, calls, _ = self.invoke([META, [dict(FILE, filename=name)], META], names=(name,))
        self.assertEqual(code, 1)
        self.assertTrue(report['api_consistent'])
        self.assertEqual(report['selection'], [name])
        self.assertFalse(any(name in argument for call in calls for argument in call))

    def test_response_failure_does_not_echo_errors_or_environment(self):
        code, report, _, _ = self.invoke([])
        self.assertEqual(code, 1)
        self.assertEqual(report['reasons'], ['api_request_failed'])
        self.assertNotIn('LEAK_SENTINEL', json.dumps(report))

    def test_output_cap_never_returns_complete(self):
        item = dict(FILE, additions=1000, deletions=0, changes=1000,
                    patch='@@ -0,0 +1,1000 @@\n' + '\n'.join(['+line'] * 1000))
        meta = dict(META, additions=1000, deletions=0)
        code, report, _, size = self.invoke([meta, [item], meta], extra=('--max-output-bytes', '1024'))
        self.assertEqual(code, 1)
        self.assertLessEqual(size, 1024)
        self.assertEqual(report['reasons'], ['output_limit'])

    def test_invalid_target_does_not_call_api(self):
        for target in [('owner/repo',), ('https://example.com/owner/repo/pull/12',),
                       ('owner/repo', 'not-a-number'), ('https://github.com/owner/repo/pull/nope',)]:
            with self.subTest(target=target):
                code, report, calls, _ = self.invoke([], target=target)
                self.assertEqual(code, 1)
                self.assertEqual(calls, [])
                self.assertEqual(report['reasons'], ['invalid_arguments'])

    def test_invalid_output_cap_does_not_call_api(self):
        code, report, calls, _ = self.invoke([], extra=('--max-output-bytes', '0'))
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertEqual(report['reasons'], ['invalid_arguments'])


if __name__ == '__main__':
    unittest.main()
