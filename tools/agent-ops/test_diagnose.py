"""診断の道具（diagnose.py）を、過去の取り違えの観測と1件の実観測で確かめる。

過去に「1つの実行面の1つの信号だけで無いと結論した」事例を fixture として再生し、
判定がその誤りを繰り返さないことを検査する。
"""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import diagnose

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures-diagnose"
SCRIPT = HERE / "diagnose.py"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


class VerdictFromFixturesTest(unittest.TestCase):
    def test_past_ollama_deleted_binary_is_not_not_installed(self):
        observation = load_fixture("past-ollama-deleted-binary.json")

        result = diagnose.verdict(observation)

        self.assertNotEqual(result.name, diagnose.VERDICT_NOT_INSTALLED)
        self.assertEqual(result.name, diagnose.VERDICT_BINARY_MISSING_PROCESS_RUNNING)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("4312", result.message)
        self.assertIn(
            "/opt/homebrew/Cellar/ollama/0.40.14/libexec/ollama", result.message
        )

    def test_past_path_only_is_path_resolution_failure(self):
        observation = load_fixture("past-path-only.json")

        result = diagnose.verdict(observation)

        self.assertEqual(result.name, diagnose.VERDICT_PATH_RESOLUTION_FAILURE)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("/opt/homebrew/bin/ollama", result.message)

    def test_correct_ok(self):
        result = diagnose.verdict(load_fixture("correct-ok.json"))

        self.assertEqual(result.name, diagnose.VERDICT_OK)
        self.assertEqual(result.exit_code, 0)

    def test_correct_missing(self):
        result = diagnose.verdict(load_fixture("correct-missing.json"))

        self.assertEqual(result.name, diagnose.VERDICT_NOT_INSTALLED)
        self.assertEqual(result.exit_code, 1)

    def test_which_without_entity_is_inconsistent(self):
        observation = load_fixture("correct-ok.json")
        observation["resolved_exists"] = False

        result = diagnose.verdict(observation)

        self.assertEqual(result.name, diagnose.VERDICT_INCONSISTENT)
        self.assertEqual(result.exit_code, 1)

    def test_running_process_with_unknown_exe_is_inconsistent(self):
        observation = load_fixture("correct-missing.json")
        observation["processes"] = [
            {"pid": 99, "command": "ollama serve", "exe": None, "exe_exists": False}
        ]

        result = diagnose.verdict(observation)

        self.assertNotEqual(result.name, diagnose.VERDICT_NOT_INSTALLED)
        self.assertEqual(result.name, diagnose.VERDICT_INCONSISTENT)
        self.assertEqual(result.exit_code, 1)


class CliFromJsonTest(unittest.TestCase):
    def test_fixtures_produce_expected_exit_codes_and_surface(self):
        expected = {
            "past-ollama-deleted-binary.json": (
                diagnose.VERDICT_BINARY_MISSING_PROCESS_RUNNING,
                1,
            ),
            "past-path-only.json": (diagnose.VERDICT_PATH_RESOLUTION_FAILURE, 1),
            "correct-ok.json": (diagnose.VERDICT_OK, 0),
            "correct-missing.json": (diagnose.VERDICT_NOT_INSTALLED, 1),
        }
        for name, (verdict_name, exit_code) in expected.items():
            with self.subTest(fixture=name):
                completed = run_cli("--from-json", str(FIXTURES / name), "--json")

                self.assertEqual(completed.returncode, exit_code, completed.stderr)
                payload = json.loads(completed.stdout)
                self.assertEqual(payload["verdict"], verdict_name)
                self.assertEqual(payload["exit_code"], exit_code)
                self.assertEqual(payload["surface"], load_fixture(name)["surface"])
                self.assertEqual(payload["observation"]["surface"], payload["surface"])
                self.assertEqual(payload["observation"]["tool"], "ollama")

    def test_from_json_does_not_observe_the_os(self):
        with mock.patch.object(
            diagnose, "observe", side_effect=AssertionError("OS must not be observed")
        ):
            with redirect_stdout(io.StringIO()) as stdout:
                code = diagnose.main(
                    ["--from-json", str(FIXTURES / "correct-ok.json"), "--json"]
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], diagnose.VERDICT_OK)
        self.assertEqual(payload["surface"], "local-shell")

    def test_malformed_observation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text('{"tool": "ollama"}', encoding="utf-8")

            completed = run_cli("--from-json", str(path), "--json")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("missing key", completed.stderr)


class RealObservationTest(unittest.TestCase):
    def test_bin_sh_is_observed_as_ok(self):
        completed = run_cli("/bin/sh", "--json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["verdict"], diagnose.VERDICT_OK)
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["tool"], "/bin/sh")
        self.assertEqual(payload["host"], socket.gethostname())
        self.assertIsInstance(payload["surface"], str)
        self.assertTrue(payload["surface"])

        observation = payload["observation"]
        self.assertEqual(set(observation), set(diagnose.OBSERVATION_KEYS))
        self.assertIn("/opt/homebrew/bin", observation["path_entries"])
        self.assertEqual(observation["surface"], payload["surface"])
        self.assertIsInstance(observation["processes"], list)
        for process in observation["processes"]:
            self.assertEqual(set(process), set(diagnose.PROCESS_KEYS))


if __name__ == "__main__":
    unittest.main()
