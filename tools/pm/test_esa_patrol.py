import unittest
from datetime import datetime, timezone

import json
from pathlib import Path
import tempfile

import esa_patrol
from esa_patrol import complete, complete_pr, inventory_lines, ready_since, report_lines


def cleanup(**summary):
    base = {'removed_worktrees': 0, 'released_workers': 0, 'needs_judgement': 0, 'errors': 0}
    return {'summary': dict(base, **summary), 'worktrees': [], 'workers': [], 'terminals': [], 'errors': []}


class ReportTest(unittest.TestCase):
    def test_a_quiet_patrol_reports_nothing(self):
        self.assertEqual(report_lines(cleanup(), {'r#1': 'a'}, {'r#1': 'a'}, []), [])

    def test_the_first_patrol_only_records_the_open_prs(self):
        self.assertEqual(report_lines(cleanup(), {'r#1': 'a'}, None, []), [])

    def test_new_and_closed_prs_and_new_issues_are_reported(self):
        lines = report_lines(cleanup(), {'r#2': 'b'}, {'r#1': 'a'}, ['r#9 bug'])
        self.assertEqual(lines, ['新しい PR: r#2 b', '閉じた PR: r#1 a', '新しい issue: r#9 bug'])

    def test_cleanup_changes_and_judgements_are_reported_with_their_items(self):
        result = cleanup(removed_worktrees=1)
        result['worktrees'] = [{'path': '/w', 'reason': '3 条件を満たす', 'done': True}]
        lines = report_lines(result, {}, {}, [])
        self.assertEqual(lines[0], '掃除: worktree 削除 1、ワーカー解放 0、要判断 0')
        self.assertEqual(lines[1], '  - /w: 3 条件を満たす')

    def test_unreadable_lists_are_reported(self):
        lines = report_lines(cleanup(), None, {}, None)
        self.assertEqual(lines, ['PR の一覧を読めなかった', 'issue の一覧を読めなかった'])


class CompleteTest(unittest.TestCase):
    def test_a_full_page_counts_as_unread(self):
        self.assertIsNone(complete([{}] * esa_patrol.LIMIT))
        self.assertEqual(complete([{}]), [{}])
        self.assertIsNone(complete(None))


class StateTest(unittest.TestCase):
    def patrol(self, state, sent, issues):
        directory = Path(tempfile.mkdtemp())
        path = directory / 'patrol.json'
        path.write_text(json.dumps(state))
        cleanup = {'summary': {'removed_worktrees': 1, 'released_workers': 0, 'needs_judgement': 0, 'errors': 0},
                   'worktrees': [{'path': '/w', 'action': 'remove', 'reason': 'ok', 'done': True}], 'workers': [], 'terminals': [],
                   'errors': []}
        originals = (esa_patrol.orca_cleanup.inventory, esa_patrol.open_prs, esa_patrol.new_issues, esa_patrol.run,
                     esa_patrol.pr_health)
        esa_patrol.pr_health = lambda: {}
        esa_patrol.orca_cleanup.inventory = lambda *args: dict(cleanup)
        esa_patrol.open_prs = lambda: {}
        esa_patrol.new_issues = lambda since: issues
        esa_patrol.run = lambda args: '{}' if sent else None
        try:
            esa_patrol.main(['--run', 'run_x', '--state', str(path), '--log', str(directory / 'log.jsonl')])
        finally:
            (esa_patrol.orca_cleanup.inventory, esa_patrol.open_prs, esa_patrol.new_issues, esa_patrol.run,
             esa_patrol.pr_health) = originals
        return json.loads(path.read_text())

    def test_an_unsent_report_is_kept_for_the_next_patrol(self):
        state = self.patrol({'last_at': 'T0', 'prs': {}}, sent=False, issues=[])
        self.assertEqual(state['unsent'][0], '掃除: worktree 削除 1、ワーカー解放 0、要判断 0')

    def test_a_sent_report_clears_the_unsent_ones(self):
        state = self.patrol({'last_at': 'T0', 'prs': {}, 'unsent': ['old']}, sent=True, issues=[])
        self.assertEqual(state['unsent'], [])

    def test_unread_issues_keep_the_search_start(self):
        state = self.patrol({'last_at': 'T0', 'prs': {}}, sent=True, issues=None)
        self.assertEqual(state['last_at'], 'T0')


if __name__ == '__main__':
    unittest.main()


def pr(draft=False, state='SUCCESS', resolved=(True,), updated='2026-11-10T00:00:00Z', checks=('2026-11-11T00:00:00Z',)):
    return {'isDraft': draft, 'updatedAt': updated,
            'reviewThreads': {'totalCount': len(resolved), 'nodes': [{'isResolved': r} for r in resolved]},
            'commits': {'nodes': [{'commit': {'statusCheckRollup': {'state': state, 'contexts': {
                'totalCount': len(checks), 'nodes': [{'completedAt': c} for c in checks]}}}}]}}


class ReadySinceTest(unittest.TestCase):
    def test_a_mergeable_pr_is_ready_since_its_last_update_or_check(self):
        self.assertEqual(ready_since(pr()), '2026-11-11T00:00:00Z')

    def test_drafts_failing_checks_and_unresolved_threads_are_not_ready(self):
        self.assertIsNone(ready_since(pr(draft=True)))
        self.assertIsNone(ready_since(pr(state='FAILURE')))
        self.assertIsNone(ready_since(pr(resolved=(True, False))))

    def test_a_pr_with_more_threads_or_checks_than_were_read_is_incomplete(self):
        self.assertTrue(complete_pr(pr()))
        cut_threads = pr()
        cut_threads['reviewThreads']['totalCount'] = 101
        cut_checks = pr()
        cut_checks['commits']['nodes'][0]['commit']['statusCheckRollup']['contexts']['totalCount'] = 101
        self.assertFalse(complete_pr(cut_threads))
        self.assertFalse(complete_pr(cut_checks))

    def test_an_incompletely_read_repository_makes_the_inventory_unread(self):
        cut = dict(pr(), number=1, title='t')
        cut['reviewThreads'] = {'totalCount': 101, 'nodes': [{'isResolved': True}]}
        data = {'data': {'repository': {'pullRequests': {'totalCount': 1, 'nodes': [cut]}}}}
        original = esa_patrol.run_json
        esa_patrol.run_json = lambda args: data
        try:
            self.assertIsNone(esa_patrol.pr_health())
        finally:
            esa_patrol.run_json = original


class InventoryTest(unittest.TestCase):
    NOW = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)

    def health(self, since, wip=0):
        prs = [{'number': 7, 'title': 't', 'wip': False, 'ready_since': since}]
        prs += [{'number': 100 + i, 'title': 'WIP', 'wip': True, 'ready_since': None} for i in range(wip)]
        return {'j5ik2o/x': prs}

    def test_a_pr_left_mergeable_for_a_day_is_reported_once(self):
        lines, reported = inventory_lines(self.health('2026-11-11T12:00:00Z'), {}, self.NOW)
        self.assertEqual(lines, ['放置: j5ik2o/x#7 t（マージ可能になってから 36 時間）'])
        self.assertEqual(inventory_lines(self.health('2026-11-11T12:00:00Z'), reported, self.NOW)[0], [])

    def test_a_pr_mergeable_for_less_than_a_day_is_not_reported(self):
        self.assertEqual(inventory_lines(self.health('2026-11-12T12:00:00Z'), {}, self.NOW)[0], [])

    def test_five_drafts_or_wip_prs_in_a_repository_are_reported_when_the_count_changes(self):
        lines, reported = inventory_lines(self.health(None, wip=5), {}, self.NOW)
        self.assertEqual(lines, ['WIP: j5ik2o/x のドラフト・WIP の PR が 5 件'])
        self.assertEqual(inventory_lines(self.health(None, wip=5), reported, self.NOW)[0], [])
        self.assertEqual(len(inventory_lines(self.health(None, wip=6), reported, self.NOW)[0]), 1)
        self.assertEqual(inventory_lines(self.health(None, wip=4), {}, self.NOW)[0], [])
