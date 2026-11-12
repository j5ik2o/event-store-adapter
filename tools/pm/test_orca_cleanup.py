import unittest

import orca_cleanup
import json
from orca_cleanup import decide_worker, decide_worktree, exit_report, needs_judgement, observe_worktree

SAFE = {'main': False, 'seat': False, 'parallel': False, 'attached': False,
        'merged_pr': True, 'clean': True, 'unpushed_free': True}


def facts(**overrides):
    return dict(SAFE, **overrides)


class WorktreeTest(unittest.TestCase):
    def test_all_three_conditions_remove(self):
        self.assertEqual(decide_worktree(facts())[0], 'remove')

    def test_each_failed_condition_keeps(self):
        for name in ('merged_pr', 'clean', 'unpushed_free'):
            with self.subTest(name=name):
                self.assertEqual(decide_worktree(facts(**{name: False}))[0], 'keep')

    def test_unobserved_condition_keeps(self):
        for name in ('merged_pr', 'clean', 'unpushed_free'):
            with self.subTest(name=name):
                action, reason = decide_worktree(facts(**{name: None}))
                self.assertEqual(action, 'keep')
                self.assertTrue(reason.startswith('確認不能'))

    def test_main_seat_and_attached_keep(self):
        for override in ({'main': True}, {'seat': True}, {'attached': True}, {'attached': None}):
            with self.subTest(override=override):
                self.assertEqual(decide_worktree(facts(**override))[0], 'keep')

    def test_parallel_is_only_listed(self):
        self.assertEqual(decide_worktree(facts(parallel=True))[0], 'list')


WORKER = {'terminal': 'structworker_x', 'state': 'succeeded', 'stage': 'settled',
          'terminalState': 'retained', 'liveness': 'live', 'activity': 'idle', 'waitingOnHuman': 'no'}


def worker(**overrides):
    return dict(WORKER, **overrides)


class WorkerTest(unittest.TestCase):
    def test_settled_idle_not_waiting_releases(self):
        self.assertEqual(decide_worker(worker(), 'term_me')[0], 'release')

    def test_settled_exited_releases(self):
        self.assertEqual(decide_worker(worker(liveness='exited', activity=None), 'term_me')[0], 'release')

    def test_coordinator_terminal_keeps_when_run_from_another_terminal(self):
        self.assertEqual(decide_worker(worker(terminal='term_coord'), 'term_patrol', set(), {'term_coord'})[0], 'keep')

    def test_own_terminal_keeps(self):
        self.assertEqual(decide_worker(worker(terminal='term_me'), 'term_me')[0], 'keep')

    def test_unsettled_running_or_waiting_keeps(self):
        for override in ({'state': 'ready', 'stage': 'running'}, {'activity': 'working'},
                         {'waitingOnHuman': 'yes'}, {'waitingOnHuman': 'unknown'},
                         {'liveness': 'unverifiable'}):
            with self.subTest(override=override):
                self.assertEqual(decide_worker(worker(**override), 'term_me')[0], 'keep')

    def test_waiting_is_reported_as_stalled(self):
        self.assertIn('停滞', decide_worker(worker(waitingOnHuman='yes'), 'term_me')[1])

    def test_without_terminal_is_skipped(self):
        self.assertEqual(decide_worker({'state': 'succeeded', 'liveness': 'unverifiable'}, 'term_me')[0], 'skip')

    def test_terminal_released_by_a_follow_up_is_skipped(self):
        handed = {'terminal': 'structworker_x', 'state': 'succeeded', 'liveness': 'unverifiable'}
        self.assertEqual(decide_worker(handed, 'term_me', {'structworker_x'})[0], 'skip')
        self.assertEqual(decide_worker(handed, 'term_me', set())[0], 'keep')

    def test_already_released_is_skipped(self):
        self.assertEqual(decide_worker(worker(terminalState='released', liveness='exited'), 'term_me')[0], 'skip')


class ObserveTest(unittest.TestCase):
    WT = {'id': 'r::/w', 'path': '/w', 'projectId': 'github:j5ik2o/event-store-adapter-java',
          'branch': 'refs/heads/topic', 'isMainWorktree': False, 'comment': ''}

    def observe(self, prs, unpushed='', ancestor=False, fetched='new'):
        def fake_run(args, cwd=None):
            command = args[3]
            if command == 'rev-parse':
                return 'abc\n' if args[4] == 'HEAD' else fetched + '\n'
            if command == 'merge-base':
                return '' if ancestor else None
            return {'status': '', 'rev-list': unpushed, 'fetch': ''}[command]
        original_run, original_json = orca_cleanup.run, orca_cleanup.run_json
        orca_cleanup.run = fake_run
        orca_cleanup.run_json = lambda args: prs
        try:
            return observe_worktree(self.WT, 'seat', False)[0]
        finally:
            orca_cleanup.run, orca_cleanup.run_json = original_run, original_json

    def test_an_older_merged_pr_of_the_same_branch_is_not_this_head(self):
        facts = self.observe([{'number': 1, 'headRefOid': 'old'}])
        self.assertFalse(facts['merged_pr'])
        self.assertEqual(decide_worktree(facts)[0], 'keep')

    def test_the_merged_pr_of_this_head_proves_merge_and_push(self):
        facts = self.observe([{'number': 2, 'headRefOid': 'abc'}], unpushed='abc\n')
        self.assertTrue(facts['merged_pr'])
        self.assertTrue(facts['unpushed_free'])
        self.assertEqual(decide_worktree(facts)[0], 'remove')

    def test_a_head_contained_in_the_updated_merged_pr_proves_merge_and_push(self):
        facts = self.observe([{'number': 3, 'headRefOid': 'new'}], unpushed='abc\n', ancestor=True)
        self.assertTrue(facts['merged_pr'])
        self.assertTrue(facts['unpushed_free'])
        self.assertEqual(decide_worktree(facts)[0], 'remove')

    def test_a_head_beyond_the_merged_pr_keeps(self):
        facts = self.observe([{'number': 3, 'headRefOid': 'new'}], unpushed='abc\n', ancestor=False)
        self.assertFalse(facts['merged_pr'])
        self.assertEqual(decide_worktree(facts)[0], 'keep')

    def test_a_pull_ref_that_is_not_the_reported_head_keeps(self):
        facts = self.observe([{'number': 3, 'headRefOid': 'new'}], unpushed='abc\n', ancestor=True, fetched='other')
        self.assertFalse(facts['merged_pr'])

    def test_unpushed_commits_without_a_matching_pr_keep(self):
        facts = self.observe([], unpushed='abc\n')
        self.assertFalse(facts['unpushed_free'])

    def test_unreadable_pr_list_is_unverified(self):
        facts = self.observe(None)
        self.assertIsNone(facts['merged_pr'])
        self.assertTrue(decide_worktree(facts)[1].startswith('確認不能'))


class JudgementTest(unittest.TestCase):
    def test_unverified_attachment_needs_judgement(self):
        action, reason = decide_worktree(facts(attached=None))
        self.assertTrue(needs_judgement(action, reason))

    def test_plain_keeps_do_not_need_judgement(self):
        self.assertFalse(needs_judgement('keep', 'coordinator のターミナル'))
        self.assertTrue(needs_judgement('list', '並列 worktree'))


class ExitReportTest(unittest.TestCase):
    def line(self, at, liveness, waiting='unknown', completed='2026-11-12T10:00:00Z', dispatch='ctx_1'):
        return json.dumps({'at': 'inventory start', 'observations': [{
            'dispatch': dispatch, 'state': 'succeeded', 'liveness': liveness, 'waitingOnHuman': waiting,
            'agent': 'claude', 'completedAt': completed, 'observed_from': at, 'observed_to': at}]})

    def test_bounds_the_time_from_completion_to_exit(self):
        report = exit_report([self.line('2026-11-12T10:30:00+00:00', 'live'),
                              self.line('2026-11-12T11:00:00+00:00', 'exited'),
                              self.line('2026-11-12T11:30:00+00:00', 'exited')])
        row = report['workers'][0]
        self.assertEqual((row['exit_after_seconds_min'], row['exit_after_seconds_max']), (1800, 3600))
        self.assertEqual(report['waitingOnHuman_while_live'], {'unknown': 1})
        self.assertEqual((report['measured'], report['still_live']), (1, 0))

    def test_a_worker_still_live_has_no_upper_bound(self):
        row = exit_report([self.line('2026-11-12T10:30:00+00:00', 'live', 'no')])['workers'][0]
        self.assertIsNone(row['exit_after_seconds_max'])
        self.assertEqual(row['waitingOnHuman_while_live'], {'no': 1})

    def test_a_missing_completion_time_is_filled_by_a_later_observation(self):
        report = exit_report([self.line('2026-11-12T10:30:00+00:00', 'live', completed=None),
                              self.line('2026-11-12T11:00:00+00:00', 'exited')])
        self.assertEqual(report['workers'][0]['exit_after_seconds_max'], 3600)

    def test_bounds_use_the_observation_window_not_the_inventory_start(self):
        line = json.dumps({'at': '2026-11-12T10:00:00+00:00', 'observations': [{
            'dispatch': 'ctx_3', 'state': 'succeeded', 'liveness': 'exited', 'completedAt': '2026-11-12T10:00:00Z',
            'observed_from': '2026-11-12T10:01:00+00:00', 'observed_to': '2026-11-12T10:05:00+00:00'}]})
        self.assertEqual(exit_report([line])['workers'][0]['exit_after_seconds_max'], 300)

    def test_workers_never_seen_live_are_counted_apart(self):
        report = exit_report([self.line('2026-11-12T11:00:00+00:00', 'exited', dispatch='ctx_4'),
                              self.line('2026-11-12T11:00:00+00:00', 'unverifiable', dispatch='ctx_5')])
        self.assertEqual((report['measured'], report['exited_before_first_observation'],
                          report['liveness_not_observed']), (0, 1, 1))

    def test_unsettled_workers_are_not_counted(self):
        line = json.dumps({'at': '2026-11-12T10:30:00+00:00', 'observations': [
            {'dispatch': 'ctx_2', 'state': 'ready', 'liveness': 'live'}]})
        self.assertEqual(exit_report([line])['workers'], [])


if __name__ == '__main__':
    unittest.main()
