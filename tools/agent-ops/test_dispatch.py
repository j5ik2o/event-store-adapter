"""Check dispatch.py against the recorded past mistakes; Orca is never called."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
FIXTURES = TOOLS / "fixtures-dispatch"
DISPATCH = TOOLS / "dispatch.py"


class DispatchTests(unittest.TestCase):
    def run_dispatch(self, *arguments):
        command = [sys.executable, str(DISPATCH), *[str(argument) for argument in arguments]]
        return subprocess.run(command, capture_output=True, text=True)

    # --- plan ---

    def test_past_duplicate_verification_fails(self):
        result = self.run_dispatch("plan", FIXTURES / "past-duplicate-verification.json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("track agent-ops-review:", result.stderr)
        self.assertIn("duplicate verification", result.stderr)
        self.assertIn("track 'agent-ops-tool'", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_correct_plan_passes(self):
        result = self.run_dispatch("plan", FIXTURES / "correct-plan.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "dispatch plan: OK (2 tracks)\n")
        self.assertEqual(result.stderr, "")

    def test_plan_rejects_overlapping_scopes_and_repeated_values(self):
        plan = {
            "goal": "Exercise the plan invariants that no fixture reaches.",
            "tracks": [
                {
                    "id": "alpha",
                    "phase": "implement",
                    "worktree": "wt-alpha",
                    "scope": ["tools/agent-ops"],
                    "verification": "cmd one",
                },
                {
                    "id": "beta",
                    "phase": "implement",
                    "worktree": "wt-beta",
                    "scope": ["tools/agent-ops/lib"],
                    "verification": "cmd two",
                },
                {
                    "id": "gamma",
                    "phase": "review",
                    "worktree": "wt-alpha",
                    "scope": ["spec"],
                    "verification": "cmd three",
                },
                {
                    "id": "beta",
                    "phase": "review",
                    "worktree": "wt-delta",
                    "scope": ["tests"],
                    "verification": "cmd four",
                },
            ],
        }
        with tempfile.TemporaryDirectory(prefix="dispatch-plan-") as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            result = self.run_dispatch("plan", path)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("track beta: duplicate id", result.stderr)
        self.assertIn("track gamma: duplicate worktree 'wt-alpha'", result.stderr)
        self.assertIn(
            "track beta: scope 'tools/agent-ops/lib'"
            " overlaps track 'alpha' scope 'tools/agent-ops'",
            result.stderr,
        )

    # --- claims ---

    def test_past_claim_without_terminal_fails(self):
        result = self.run_dispatch(
            "claims",
            FIXTURES / "past-claim-with-terminal.json",
            "--terminals",
            FIXTURES / "past-terminals.json",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("track agent-ops-tool:", result.stderr)
        self.assertIn("terminal 'term_missing' is not listed by Orca", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_correct_claims_pass(self):
        result = self.run_dispatch(
            "claims",
            FIXTURES / "correct-claims.json",
            "--terminals",
            FIXTURES / "correct-terminals.json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "dispatch claims: OK (2 claims)\n")
        self.assertEqual(result.stderr, "")

    # --- check ---

    def test_check_correct_files_pass(self):
        result = self.run_dispatch(
            "check",
            FIXTURES / "correct-plan.json",
            FIXTURES / "correct-claims.json",
            "--terminals",
            FIXTURES / "correct-terminals.json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "dispatch plan: OK (2 tracks)\n"
            "dispatch claims: OK (2 claims)\n",
        )
        self.assertEqual(result.stderr, "")

    def test_check_reports_a_failing_plan(self):
        result = self.run_dispatch(
            "check",
            FIXTURES / "past-duplicate-verification.json",
            FIXTURES / "correct-claims.json",
            "--terminals",
            FIXTURES / "correct-terminals.json",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("track agent-ops-review: duplicate verification", result.stderr)


if __name__ == "__main__":
    unittest.main()
