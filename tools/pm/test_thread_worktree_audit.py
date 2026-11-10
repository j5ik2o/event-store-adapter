"""Behavior tests use saved snapshots and the real CLI, with no repository creation."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads((HERE / 'thread_worktree_examples.json').read_text(encoding='utf-8'))

    def run_cli(self, example=None, raw=None):
        data = example or self.example
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name in ('export', 'git', 'ledger'):
                path = Path(tmp) / (name + '.json')
                path.write_text(raw if name == 'export' and raw is not None else
                                json.dumps(data[name]), encoding='utf-8')
                paths.append(str(path))
            run = subprocess.run([sys.executable, str(HERE / 'thread_worktree_audit.py'),
                                  'check', paths[0], paths[1], '--ledger', paths[2]],
                                 capture_output=True, text=True)
            result = json.loads(run.stdout)
            self.assertEqual(bool(run.stderr), run.returncode != 0)
            return run.returncode, result

    def test_complete_unicode_paths_still_retain_without_cleanup_evidence(self):
        code, r = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(r['status'], 'consistent')
        self.assertEqual([t['role'] for t in r['trees']], ['root', 'audit'])
        self.assertEqual(r['threads'][1]['git_comparison'], 'match')
        self.assertEqual(r['threads'][0]['status'], 'idle')
        for tree in r['trees']:
            self.assertEqual(tree['cleanup'], 'retain')
            self.assertEqual(tree['cleanup_conditions']['post_merge_main_CI_success'], 'unknown')

    def test_top_only_missing_page_failure_duplicate_and_broken_graph(self):
        variants = []
        d = copy.deepcopy(self.example); d['export']['includeSubagents'] = False
        variants.append((d, 'includeSubagents_not_true'))
        d = copy.deepcopy(self.example); d['export']['pages'][0]['nextCursor'] = 2
        variants.append((d, 'incomplete_pagination_or_total'))
        d = copy.deepcopy(self.example); d['export']['pages'].append({'error': 'API failure'})
        variants.append((d, 'page_failure:1'))
        d = copy.deepcopy(self.example); d['export']['pages'][0]['threads'].append(d['export']['pages'][0]['threads'][0])
        variants.append((d, 'duplicate_thread:pm'))
        d = copy.deepcopy(self.example); d['export']['pages'][0]['threads'][1]['parentThreadId'] = 'missing'
        variants.append((d, 'missing_parent:child'))
        for d, issue in variants:
            with self.subTest(issue=issue):
                code, r = self.run_cli(d)
                self.assertEqual(code, 1)
                self.assertIn(issue, r['issues'])
                self.assertEqual(len(r['threads']), 2)
                self.assertEqual(r['trees'][0]['observations']['head']['value'], 'a'*40)

    def test_path_foreign_origin_and_branch_mismatch(self):
        for field, value, issue in [('worktreePath', '/does/not/exist', 'worktree_not_observed:child'),
                                    ('branch', 'wrong', 'worktree_mismatch:child')]:
            d = copy.deepcopy(self.example); d['export']['metadata'][1][field] = value
            code, r = self.run_cli(d)
            self.assertEqual(code, 1); self.assertIn(issue, r['issues'])
        d = copy.deepcopy(self.example)
        d['git']['repositories'][0]['trees'][1]['observations']['origin']['value'] = 'github.com/other/repo'
        code, r = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertIn('worktree_mismatch:child', r['issues'])

    def test_all_lifecycle_states_remain_distinct(self):
        for status in ('idle', 'running', 'waiting', 'interrupted', 'failed', 'completed',
                       'cancelled', 'rolled_back', 'queued', 'starting', 'preparing'):
            d = copy.deepcopy(self.example)
            d['export']['pages'][0]['threads'][1]['status'] = status
            d['export']['metadata'][1]['status'] = status
            code, r = self.run_cli(d)
            self.assertEqual(code, 0)
            self.assertEqual(r['threads'][1]['status'], status)
            self.assertEqual(r['threads'][1]['stale'], 'not_assessed_single_observation')
            self.assertEqual(r['trees'][1]['cleanup'], 'retain')

    def test_unknown_git_and_missing_repository_keep_known_commits(self):
        d = copy.deepcopy(self.example)
        d['git']['repositories'][0]['trees'][1]['observations']['upstream'] = {'error': 'no upstream'}
        d['ledger']['repositories'].append({'repo': 'j5ik2o/missing'})
        code, r = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertIn('missing_repository:j5ik2o/missing', r['issues'])
        self.assertEqual(r['trees'][1]['observations']['head']['value'], 'a'*40)

    def test_json_boundary_rejects_single_defect_in_valid_control(self):
        raw = json.dumps(self.example['export'])
        variants = [raw.replace('"schema_version": 1', '"schema_version": true'),
                    raw.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
                    raw.replace('"total": 2', '"total": true'),
                    raw.replace('"includeSubagents": true', '"includeSubagents": null'),
                    raw.replace('"status": "idle"', '"status": "unknown"', 1),
                    raw.replace('"cursor": null', '"cursor": false')]
        for bad in variants:
            self.assertNotEqual(bad, raw)
            code, r = self.run_cli(raw=bad)
            self.assertEqual(code, 2)
            self.assertEqual(r['status'], 'invalid_input')

    def test_malformed_listing_and_pending_count_are_structured_errors(self):
        for listing in ({'value': None}, {'value': 3}, {}, {'error': False}):
            d = copy.deepcopy(self.example)
            d['git']['repositories'][0]['listing'] = listing
            code, r = self.run_cli(d)
            self.assertEqual(code, 2)
            self.assertEqual(len(r['threads']), 2)
        d = copy.deepcopy(self.example)
        d['export']['metadata'][1]['pendingRequestCount'] = True
        code, r = self.run_cli(d)
        self.assertEqual(code, 2)
        self.assertEqual(len(r['threads']), 2)

    def test_readonly_git_capture_existing_checkout(self):
        checkout = Path(os.environ.get('THREAD_AUDIT_TEST_CHECKOUT', str(HERE.parent.parent)))
        head = subprocess.run(['git', '-C', str(checkout), 'rev-parse', '--verify', 'HEAD'],
                              capture_output=True, text=True)
        if head.returncode:
            self.skipTest('set THREAD_AUDIT_TEST_CHECKOUT to an existing Git checkout')
        with tempfile.TemporaryDirectory() as tmp:
            roots = Path(tmp) / 'roots.json'
            roots.write_text(json.dumps({'host_aliases': {'j5ik2o.github.com': 'github.com'},
                'repositories': [{'repo': 'j5ik2o/event-store-adapter', 'root': str(checkout)}]}), encoding='utf-8')
            run = subprocess.run([sys.executable, str(HERE / 'thread_worktree_audit.py'),
                'observe-git', str(roots)], capture_output=True, text=True)
            self.assertIn(run.returncode, (0, 1))
            records = json.loads(run.stdout)['repositories'][0]
            tree = next(t for t in records['trees'] if t['path'] == str(checkout))
            self.assertEqual(tree['observations']['head']['value'], head.stdout.strip())
            origin = tree['observations']['origin']
            self.assertIn(set(origin), ({'value'}, {'error'}))
            self.assertIsInstance(next(iter(origin.values())), str)
            self.assertIn('value', tree['observations']['status'])

    def test_saved_origin_credentials_not_echoed(self):
        d = copy.deepcopy(self.example)
        d['git']['repositories'][0]['trees'][1]['observations']['origin']['value'] = 'https://secret:credential@github.com/a/b'
        code, r = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertNotIn('credential', json.dumps(r))

    def test_malformed_git_field_keeps_known_and_following_trees(self):
        for index in (0, 1):
            for field, bad in [('status', {'value': None}), ('upstream', {'error': False})]:
                d = copy.deepcopy(self.example)
                d['git']['repositories'][0]['trees'][index]['observations'][field] = bad
                code, r = self.run_cli(d)
                self.assertEqual(code, 2)
                self.assertEqual([t['path'] for t in r['trees']],
                                 [t['path'] for t in d['git']['repositories'][0]['trees']])
                self.assertEqual(r['trees'][index]['observations']['head']['value'], 'a'*40)
                self.assertIn('error', r['trees'][index]['observations'][field])
                self.assertEqual(r['trees'][index]['cleanup'], 'retain')

    def test_malformed_listing_keeps_independent_tree_observations(self):
        d = copy.deepcopy(self.example)
        d['git']['repositories'][0]['listing'] = {'value': None}
        code, r = self.run_cli(d)
        self.assertEqual(code, 2)
        self.assertEqual(len(r['trees']), 2)
        self.assertEqual(r['trees'][1]['observations']['head']['value'], 'a'*40)

    def test_duplicate_metadata_keeps_paths_and_reports_ambiguity(self):
        for later in ({'threadId': 'child', 'error': 'later failed'},
                      dict(self.example['export']['metadata'][1], status='failed',
                           worktreePath='/other/tree')):
            d = copy.deepcopy(self.example)
            d['export']['metadata'].append(later)
            code, r = self.run_cli(d)
            self.assertEqual(code, 1)
            child = r['threads'][1]
            self.assertEqual(child['metadata']['worktreePath'], '/example/監査 tree')
            self.assertEqual(len(child['metadata_observations']), 2)
            self.assertEqual(child['git_comparison'], 'ambiguous')
            self.assertIn('child', r['trees'][1]['owners'])
            if 'error' in later:
                self.assertIn('error', child['metadata_observations'][1])
            else:
                self.assertEqual(child['metadata_observations'][1]['status'], 'failed')
                self.assertEqual(r['trees'][1]['cleanup_conditions']
                                 ['no_failed_interrupted_waiting_owner'], 'observed_false')

    def test_duplicate_thread_retains_conflicting_lifecycle(self):
        d = copy.deepcopy(self.example)
        d['export']['pages'][0]['threads'].append(
            dict(d['export']['pages'][0]['threads'][1], status='failed'))
        code, r = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertIn('list_observations', r['threads'][1])
        self.assertEqual([t['status'] for t in r['threads'][1]['list_observations']],
                         ['completed', 'failed'])
        self.assertEqual(r['threads'][1]['git_comparison'], 'ambiguous')
        self.assertEqual(r['trees'][1]['cleanup_conditions']
                         ['no_failed_interrupted_waiting_owner'], 'observed_false')

    def test_explicit_metadata_project_conflict_is_not_consistent(self):
        d = copy.deepcopy(self.example)
        d['export']['metadata'][1]['projectId'] = 'foreign'
        code, r = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertIn('metadata_project_mismatch:child', r['issues'])
        self.assertEqual(r['threads'][1]['metadata_observations'][0]['projectId'], 'foreign')
        self.assertEqual(r['threads'][1]['git_comparison'], 'ambiguous')
        del d['export']['metadata'][1]['projectId']
        self.assertEqual(self.run_cli(d)[0], 0)

    def test_invalid_metadata_field_preserves_independent_path(self):
        d = copy.deepcopy(self.example)
        d['export']['metadata'][1]['pendingRequestCount'] = True
        code, r = self.run_cli(d)
        self.assertEqual(code, 2)
        self.assertEqual(r['threads'][1]['metadata']['worktreePath'], '/example/監査 tree')
        self.assertEqual(r['threads'][1]['git_comparison'], 'ambiguous')
        self.assertIn('child', r['trees'][1]['owners'])

    def test_empty_or_rootless_git_listing_cannot_cover_repository(self):
        for empty in (True, False):
            d = copy.deepcopy(self.example)
            if empty:
                d['ledger']['repositories'].append({'repo': 'other/unobserved'})
                d['git']['repositories'].append(dict(repo='other/unobserved',
                    root='/missing/root', listing={'value': ''}, trees=[]))
                repo = 'other/unobserved'
            else:
                d['git']['repositories'][0]['root'] = '/missing/root'
                repo = d['git']['repositories'][0]['repo']
            code, r = self.run_cli(d)
            self.assertEqual(code, 1)
            self.assertIn('git_tree_coverage:' + repo, r['issues'])

    def test_unlisted_metadata_keeps_failure_path_and_candidate_owner(self):
        d = copy.deepcopy(self.example)
        d['export']['pages'][0]['threads'].pop()
        d['export']['pages'][0]['total'] = 1
        d['export']['metadata'][1].update(status='failed', pendingRequestCount=1)
        code, r = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertFalse(r['inventory_complete'])
        self.assertEqual([t['threadId'] for t in r['threads']], ['pm'])
        self.assertIn('unlisted_metadata', r)
        missing = r['unlisted_metadata'][0]
        self.assertEqual(missing['threadId'], 'child')
        self.assertEqual(missing['listing_membership'], 'unverified')
        observation = missing['observations'][0]
        self.assertEqual(observation['status'], 'failed')
        self.assertEqual(observation['pendingRequestCount'], 1)
        self.assertEqual(observation['worktreePath'], '/example/監査 tree')
        self.assertIn('child', r['trees'][1]['owners'])
        self.assertEqual(r['trees'][1]['cleanup_conditions']
                         ['no_failed_interrupted_waiting_owner'], 'observed_false')
        self.assertEqual(r['trees'][1]['cleanup'], 'retain')


if __name__ == '__main__':
    unittest.main()
