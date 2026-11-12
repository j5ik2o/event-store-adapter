import unittest

from orca_cleanup import decide_worker, decide_worktree

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


if __name__ == '__main__':
    unittest.main()
