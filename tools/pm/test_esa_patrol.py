import unittest

import json
from pathlib import Path
import tempfile

import esa_patrol
from esa_patrol import complete, report_lines


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
        originals = (esa_patrol.orca_cleanup.inventory, esa_patrol.open_prs, esa_patrol.new_issues, esa_patrol.run)
        esa_patrol.orca_cleanup.inventory = lambda *args: dict(cleanup)
        esa_patrol.open_prs = lambda: {}
        esa_patrol.new_issues = lambda since: issues
        esa_patrol.run = lambda args: '{}' if sent else None
        try:
            esa_patrol.main(['--run', 'run_x', '--state', str(path), '--log', str(directory / 'log.jsonl')])
        finally:
            (esa_patrol.orca_cleanup.inventory, esa_patrol.open_prs, esa_patrol.new_issues, esa_patrol.run) = originals
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
