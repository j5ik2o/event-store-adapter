"""Exercise the real CLI as an auditor who must reject false completeness."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).with_name("repository_coverage.py")
LEDGER = Path(__file__).with_name("repository_coverage_ledger.json")
NAMES = [row["repo"].split("/")[1] for row in json.loads(LEDGER.read_text())["repositories"]]


class CoverageCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inventory = {"at": "2026-11-10T15:09:36+00:00", "results": []}
        for name in NAMES:
            self.inventory["results"].append(dict(repo=name, prs=0, issues=0, milestones=[], pagination=[]))
            self.write_raw(name, {"data": {"repository": dict(name=name, **{
                key: {"nodes": [], "pageInfo": {"hasNextPage": False}}
                for key in ("pullRequests", "issues", "milestones")})}})

    def write_raw(self, name, value):
        (self.root / (name + ".json")).write_text(json.dumps(value))

    def run_cli(self, code):
        path = self.root / "inventory.json"
        path.write_text(json.dumps(self.inventory))
        process = subprocess.run([sys.executable, str(CLI), "--inventory", str(path),
                                  "--records-dir", str(self.root)], capture_output=True, text=True)
        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_all_sixteen_success_including_zero_open_items(self):
        result = self.run_cli(0)
        self.assertEqual(len(result["successful"]), 16)
        self.assertEqual(result["status"], "consistent")

    def test_reconstructed_example_omission_reports_seven_names(self):
        self.inventory = json.loads(CLI.with_name("repository_coverage_missing_examples.json").read_text())
        result = self.run_cli(1)
        self.assertEqual(result["missing"], sorted("j5ik2o/" + n for n in NAMES if n.startswith("cqrs")))
        self.assertEqual(len(result["successful"]), 9)

    def test_checkout_based_omission_cannot_hide_dotnet_php(self):
        self.inventory["results"] = [r for r in self.inventory["results"] if not r["repo"].endswith(("-dotnet", "-php"))]
        self.assertEqual(self.run_cli(1)["missing"], ["j5ik2o/event-store-adapter-dotnet", "j5ik2o/event-store-adapter-php"])

    def test_extra_and_duplicate_are_separate_from_missing(self):
        self.inventory["results"].append(copy.deepcopy(self.inventory["results"][0]))
        extra = dict(repo="unmanaged", prs=0, issues=0, milestones=[], pagination=[])
        self.inventory["results"].append(extra)
        raw = json.loads((self.root / (NAMES[0] + ".json")).read_text())
        raw["data"]["repository"]["name"] = "unmanaged"
        self.write_raw("unmanaged", raw)
        result = self.run_cli(1)
        self.assertEqual(result["unexpected"], ["j5ik2o/unmanaged"])
        self.assertEqual(result["duplicates"], ["j5ik2o/event-store-adapter"])
        self.assertEqual(result["missing"], [])
        self.assertNotIn("j5ik2o/event-store-adapter", result["successful"])

    def test_named_failure_is_observed_but_not_success(self):
        self.inventory["results"][0] = {"repo": NAMES[0], "error": "authentication failed"}
        result = self.run_cli(1)
        self.assertEqual(result["failed"][0]["repo"], "j5ik2o/event-store-adapter")
        self.assertEqual(result["missing"], [])
        self.assertEqual(len(result["successful"]), 15)

    def test_partial_graphql_error_overrides_plausible_repository(self):
        path = self.root / (NAMES[0] + ".json")
        raw = json.loads(path.read_text())
        raw["errors"] = [{"message": "rate limit"}]
        self.write_raw(NAMES[0], raw)
        self.assertIn("GraphQL", self.run_cli(1)["failed"][0]["reason"])

    def test_nested_pagination_prevents_success(self):
        path = self.root / (NAMES[0] + ".json")
        raw = json.loads(path.read_text())
        raw["data"]["repository"]["issues"]["nodes"] = [{"comments": {"nodes": [], "pageInfo": {"hasPreviousPage": True}}}]
        self.inventory["results"][0]["issues"] = 1
        self.write_raw(NAMES[0], raw)
        self.assertIn("comments", self.run_cli(1)["incomplete"][0]["reason"])

    def test_unusable_evidence_never_passes_by_repo_name(self):
        for raw in ({}, None, {"data": {"repository": None}}, {"data": {"repository": {"name": NAMES[0]}}}):
            with self.subTest(raw=raw):
                self.write_raw(NAMES[0], raw)
                self.assertEqual(len(self.run_cli(2)["invalid_records"]), 1)

    def test_inconsistent_count_is_not_complete(self):
        self.inventory["results"][0]["prs"] = 1
        self.assertIn("count mismatch", self.run_cli(2)["invalid_records"][0]["reason"])

    def test_missing_raw_and_invalid_pagination(self):
        path = self.root / (NAMES[0] + ".json")
        raw = json.loads(path.read_text())
        path.unlink()
        self.assertEqual(len(self.run_cli(2)["invalid_records"]), 1)
        raw["data"]["repository"]["issues"]["pageInfo"]["hasNextPage"] = "false"
        self.write_raw(NAMES[0], raw)
        self.assertEqual(len(self.run_cli(2)["invalid_records"]), 1)

    def test_empty_and_malformed_inventory(self):
        for value in ({}, [], {"at": self.inventory["at"], "results": []},
                      {"at": "2026-11-10", "results": self.inventory["results"]}):
            with self.subTest(value=value):
                original = self.inventory
                self.inventory = value
                self.assertEqual(self.run_cli(2)["status"], "invalid_input")
                self.inventory = original

    def test_input_command_is_never_executed(self):
        sentinel = self.root / "executed"
        self.inventory["results"][0]["error"] = f"touch {sentinel}"
        self.run_cli(1)
        self.assertFalse(sentinel.exists())

    def test_duplicate_json_keys_are_rejected(self):
        (self.root / (NAMES[0] + ".json")).write_text('{"data":null,"data":{}}')
        self.assertIn("duplicate JSON key", self.run_cli(2)["invalid_records"][0]["reason"])

    def test_wrong_identity_and_path_traversal(self):
        self.write_raw(NAMES[0], {"data": {"repository": {"name": "other"}}})
        self.assertIn("name mismatch", self.run_cli(2)["invalid_records"][0]["reason"])
        self.inventory["results"][0]["repo"] = "../outside"
        self.assertEqual(self.run_cli(2)["status"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
