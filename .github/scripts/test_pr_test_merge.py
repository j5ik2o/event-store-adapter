#!/usr/bin/env python3
"""Regression tests for pr-test-merge.sh and the PR CI workflow that calls it."""

import os
import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("PR_TEST_MERGE_SCRIPT", HERE / "pr-test-merge.sh"))
WORKFLOW = HERE.parent / "workflows" / "aislop-check.yml"


class PullRequestTestMergeTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.origin = self.root / "origin.git"
        self.git(None, "init", "-q", "--bare", str(self.origin))
        common = self.commit({"a": "1\n", "b": "1\n"})
        self.old_base = self.commit({"a": "1\n", "b": "1\n", "old": "x\n"}, common)
        self.base = self.commit({"a": "2\n", "b": "1\n", "old": "x\n"}, self.old_base)
        self.old_head = self.commit({"a": "1\n", "b": "2\n"}, common)
        self.head = self.commit({"a": "1\n", "b": "3\n"}, self.old_head)
        self.set_ref("refs/heads/main", self.base)
        self.set_ref("refs/pull/1/head", self.head)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_PR"\n')
        (bin_dir / "gh").chmod(0o755)
        # Runs between re-fetches of the candidate, so a test can change the remote meanwhile.
        (bin_dir / "sleep").write_text('#!/bin/sh\necho >> "$FIXTURE_SLEEPS"\neval "$FIXTURE_ON_SLEEP"\n')
        (bin_dir / "sleep").chmod(0o755)
        self.sleeps = self.root / "sleeps"
        self.path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    def git(self, cwd, *args, **kwargs):
        return subprocess.run(
            ["git", *(["-C", str(cwd)] if cwd else []), "-c", "user.name=Fixture",
             "-c", "user.email=fixture@example.com", *args],
            text=True, capture_output=True, check=True, **kwargs,
        ).stdout.strip()

    def commit(self, files, *parents, message="fixture"):
        entries = "".join(
            f"100644 blob {self.git(self.origin, 'hash-object', '-w', '--stdin', input=text)}\t{name}\n"
            for name, text in sorted(files.items()))
        tree = self.git(self.origin, "mktree", input=entries)
        parent_args = [arg for parent in parents for arg in ("-p", parent)]
        return self.git(self.origin, "commit-tree", tree, *parent_args, "-m", message)

    def set_ref(self, ref, sha):
        self.git(self.origin, "update-ref", ref, sha)

    def github_merge(self, base, head):
        """Store the candidate that GitHub offers as refs/pull/1/merge."""
        tree = self.git(self.origin, "merge-tree", "--write-tree", base, head)
        merge = self.git(self.origin, "commit-tree", tree, "-p", base, "-p", head, "-m", "merge")
        self.set_ref("refs/pull/1/merge", merge)
        return merge

    def run_script(self, *, event_base, event_head, api_head=None, checkout=None, **extra_env):
        """Check out the event's merge as actions/checkout does, then run the script."""
        runner = self.root / "runner"
        subprocess.run(["rm", "-rf", str(runner)], check=True)
        self.git(None, "init", "-q", str(runner))
        self.git(runner, "remote", "add", "origin", self.origin.as_uri())
        self.git(runner, "fetch", "-q", "--no-tags", "--depth=1", "origin",
                 checkout or "refs/pull/1/merge")
        self.git(runner, "checkout", "-q", "--detach", "FETCH_HEAD")
        env = dict(os.environ, PATH=self.path, PR_NUMBER="1", GITHUB_REPOSITORY="fixture/repo",
                   EVENT_HEAD_SHA=event_head, BASE_SHA=event_base, HEAD_SHA=event_head,
                   MERGE_REFETCHES="1", MERGE_RETRY_SECONDS="0", GH_TOKEN="fixture",
                   FIXTURE_PR=f"open\tmain\t{api_head or self.head}",
                   FIXTURE_SLEEPS=str(self.sleeps), FIXTURE_ON_SLEEP="")
        env.update(extra_env)
        result = subprocess.run(["bash", str(SCRIPT)], cwd=runner, env=env,
                                capture_output=True, text=True, timeout=60)
        head = self.git(runner, "rev-parse", "HEAD")
        parents = self.git(runner, "cat-file", "-p", head).split("\n\n", 1)[0]
        return result, head, re.findall(r"^parent (\w+)$", parents, re.M)

    def assert_checks_current_merge(self, result, parents):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(parents, [self.base, self.head])

    def test_uses_a_current_github_candidate(self):
        merge = self.github_merge(self.base, self.head)
        result, head, parents = self.run_script(event_base=self.base, event_head=self.head)
        self.assert_checks_current_merge(result, parents)
        self.assertEqual(head, merge)

    def test_ignores_an_old_base_in_the_event(self):
        self.github_merge(self.base, self.head)
        result, _, parents = self.run_script(event_base=self.old_base, event_head=self.head)
        self.assert_checks_current_merge(result, parents)

    def test_builds_the_merge_when_the_github_candidate_keeps_an_old_base(self):
        for event_base in (self.base, self.old_base):
            with self.subTest(event_base=event_base):
                stale = self.github_merge(self.old_base, self.head)
                result, head, parents = self.run_script(event_base=event_base, event_head=self.head)
                self.assert_checks_current_merge(result, parents)
                self.assertNotEqual(head, stale)
                self.assertIn("building the test merge", result.stdout)

    def test_builds_the_same_merge_on_every_run(self):
        self.github_merge(self.old_base, self.head)
        first = self.run_script(event_base=self.old_base, event_head=self.head)
        second = self.run_script(event_base=self.old_base, event_head=self.head)
        for result, _, parents in (first, second):
            self.assert_checks_current_merge(result, parents)
        self.assertEqual(first[1], second[1])

    def test_re_fetches_the_candidate_four_times_by_default(self):
        self.github_merge(self.old_base, self.head)
        result, _, parents = self.run_script(event_base=self.base, event_head=self.head,
                                             MERGE_REFETCHES="")
        self.assert_checks_current_merge(result, parents)
        self.assertEqual(len(self.sleeps.read_text().splitlines()), 4)

    def test_uses_a_github_candidate_that_becomes_current(self):
        self.github_merge(self.old_base, self.head)
        current = self.commit({"a": "2\n", "b": "3\n", "old": "x\n"}, self.base, self.head)
        result, head, parents = self.run_script(
            event_base=self.base, event_head=self.head,
            FIXTURE_ON_SLEEP=f"git --git-dir='{self.origin}' update-ref refs/pull/1/merge {current}")
        self.assert_checks_current_merge(result, parents)
        self.assertEqual(head, current)

    def move_main_during_re_fetch(self, files):
        moved = self.commit(files, self.base)
        return moved, f"git --git-dir='{self.origin}' update-ref refs/heads/main {moved}"

    def test_builds_on_a_base_that_moves_during_re_fetch(self):
        self.github_merge(self.old_base, self.head)
        moved, hook = self.move_main_during_re_fetch({"a": "2\n", "b": "1\n", "old": "x\n", "c": "1\n"})
        result, _, parents = self.run_script(event_base=self.base, event_head=self.head,
                                             FIXTURE_ON_SLEEP=hook)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(parents, [moved, self.head])

    def test_rejects_a_github_candidate_on_a_base_that_moved_during_re_fetch(self):
        self.github_merge(self.old_base, self.head)
        on_first_base = self.commit({"a": "2\n", "b": "3\n", "old": "x\n"}, self.base, self.head)
        moved, hook = self.move_main_during_re_fetch({"a": "2\n", "b": "1\n", "old": "x\n", "c": "1\n"})
        hook += f"; git --git-dir='{self.origin}' update-ref refs/pull/1/merge {on_first_base}"
        result, head, parents = self.run_script(event_base=self.base, event_head=self.head,
                                                FIXTURE_ON_SLEEP=hook)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(head, on_first_base)
        self.assertEqual(parents, [moved, self.head])

    def test_fails_when_a_base_that_moves_during_re_fetch_conflicts(self):
        self.github_merge(self.old_base, self.head)
        _, hook = self.move_main_during_re_fetch({"a": "2\n", "b": "9\n", "old": "x\n"})
        result, _, _ = self.run_script(event_base=self.base, event_head=self.head,
                                       FIXTURE_ON_SLEEP=hook)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("conflicts with main@", result.stderr)

    def test_rejects_an_event_for_an_old_head(self):
        # GitHub built the event's merge for the old head, and the head has moved since.
        self.github_merge(self.old_base, self.old_head)
        result, _, _ = self.run_script(event_base=self.old_base, event_head=self.old_head)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("is not the current head", result.stderr)

    def test_rejects_a_head_that_moves_during_the_run(self):
        self.github_merge(self.old_base, self.head)
        self.set_ref("refs/pull/1/head", self.commit({"a": "1\n", "b": "4\n"}, self.head))
        result, _, _ = self.run_script(event_base=self.base, event_head=self.head)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("the run for the current head decides", result.stderr)

    def test_fails_when_the_current_base_conflicts(self):
        self.github_merge(self.old_base, self.head)
        self.set_ref("refs/heads/main", self.commit({"a": "2\n", "b": "9\n", "old": "x\n"}, self.base))
        result, _, _ = self.run_script(event_base=self.base, event_head=self.head)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("conflicts with main@", result.stderr)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_on_every_pull_request_action(self):
        types = re.search(r"^  pull_request:\n(?:    .*\n)*?    types: \[([^\]]+)\]$", self.workflow, re.M)
        self.assertIsNotNone(types)
        self.assertCountEqual([t.strip() for t in types[1].split(",")],
                              ["opened", "synchronize", "reopened", "edited"])

    def test_checks_out_the_merge_for_every_pull_request_event(self):
        step = re.search(r"- name: Check out the current test merge\n((?:        .*\n)+)", self.workflow)
        self.assertIsNotNone(step)
        self.assertIn("if: ${{ github.event_name == 'pull_request' }}", step[1])
        self.assertIn(".github/scripts/pr-test-merge.sh", step[1])

    def test_publishes_the_required_check_whatever_the_ci_result(self):
        job = re.search(r"^  required-ci:\n((?:    .*\n|\n)+)", self.workflow, re.M)
        self.assertIsNotNone(job)
        self.assertIn("name: ESA Required CI\n", job[1])
        self.assertIn("needs: aislop-check\n", job[1])
        self.assertIn("if: ${{ always() }}\n", job[1])
        self.assertNotIn("event.action", self.workflow)

    def test_the_required_check_fails_unless_the_ci_job_succeeds(self):
        step = re.search(r"- name: Require successful CI\n(?:        .*\n)*?        run: \|\n((?:          .*\n)+)",
                         self.workflow)
        self.assertIsNotNone(step)
        script = "\n".join(line[10:] for line in step[1].splitlines())
        for result, code in (("success", 0), ("failure", 1), ("cancelled", 1), ("skipped", 1)):
            with self.subTest(result=result):
                run = subprocess.run(["bash", "-c", script], env=dict(os.environ, AISLOP_RESULT=result),
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, code, run.stderr)


if __name__ == "__main__":
    unittest.main()
