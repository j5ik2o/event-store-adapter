import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_delegations.py")


class DelegationAuditTest(unittest.TestCase):
    def run_audit(self, count, missing_start=False, completed=False):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.tsv"
            checkpoints = Path(directory) / "checkpoints.tsv"
            with ledger.open("w", newline="") as output:
                writer = csv.DictWriter(output, delimiter="\t", fieldnames=["launch", "task_id", "delegation", "issue_start_record", "issue_start_comments"])
                writer.writeheader()
                for number in range(count):
                    missing = missing_start and number == 0
                    writer.writerow(dict(launch="started", task_id=f"task-{number}", delegation=f"job-{number}", issue_start_record="missing" if missing else "present", issue_start_comments="" if missing else f"https://github.com/owner/repo/issues/1#issuecomment-{number+1}"))
            with checkpoints.open("w", newline="") as output:
                writer = csv.DictWriter(output, delimiter="\t", fieldnames=["counter", "boundary", "correct_issue_evidence", "reflect_issue_evidence"])
                writer.writeheader()
                if completed:
                    writer.writerow(dict(counter="issue-recorded-started", boundary=20, correct_issue_evidence="https://github.com/owner/repo/issues/1#issuecomment-100", reflect_issue_evidence="https://github.com/owner/repo/issues/1#issuecomment-101"))
            return subprocess.run([sys.executable, str(SCRIPT), str(ledger), str(checkpoints)], capture_output=True, text=True)

    def test_missing_start_comment_blocks_completion(self):
        result = self.run_audit(1, missing_start=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing issue start comment", result.stderr)

    def test_twentieth_record_requires_both_skill_records(self):
        result = self.run_audit(20)
        self.assertEqual(result.returncode, 1)
        self.assertIn("20: correct completion evidence missing", result.stderr)
        self.assertIn("20: reflect completion evidence missing", result.stderr)

    def test_nineteenth_record_and_completed_twentieth_record_pass(self):
        self.assertEqual(self.run_audit(19).returncode, 0)
        self.assertEqual(self.run_audit(20, completed=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
