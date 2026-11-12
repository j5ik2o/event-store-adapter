import unittest

from esa_patrol import report_lines


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


if __name__ == '__main__':
    unittest.main()
