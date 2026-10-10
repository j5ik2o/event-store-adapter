"""取得・ビルド・測定の正規入口で、入力と成功記録の対応を確認する。"""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

import build
import run


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "build"
        self.output.mkdir()
        self.pins = copy.deepcopy(build.PINS)
        self.pins["sources"] = {lang: f"{i:040x}" for i, lang in enumerate(self.pins["sources"], 1)}
        self.archives = {}
        for language, sha in self.pins["sources"].items():
            files = {"marker.txt": sha.encode()}
            if language == "go":
                files.update({"go.mod": b"module github.com/j5ik2o/event-store-adapter-go/v2\n", "go.sum": b""})
            if language == "java":
                files["src/main/java/Fixture.java"] = b"class Fixture {}\n"
            self.add_archive(language, sha, files)
        self.supplied = self.root / "supplied"
        self.supplied.mkdir()
        snapshot = self.pins["java_currentSnapshot"]
        for suffix, key in ((".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")):
            path = self.supplied / (snapshot["artifact"] + suffix)
            with zipfile.ZipFile(path, "w") as package:
                if suffix == "-sources.jar":
                    package.writestr("Fixture.java", b"class Fixture {}\n")
                else:
                    package.writestr("Fixture.class", b"fixture bytecode")
            snapshot[key] = build.digest(path)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # 外部ビルドだけを代替し、生成物の列挙・取得・成功記録は実入口に任せる。
        executable = "#!" + sys.executable + "\n" + '''
import json, os, sys
from pathlib import Path
output = Path(os.environ["INTEROP_TEST_OUTPUT"])
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
with (output / "tool-calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"tool": tool, "args": args}) + "\\n")
def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
if tool == "gradle":
    jvm = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("-PoutputDir=")))
    write(jvm / "Fixture.class", b"jvm fixture")
    write(jvm / "classpath.txt", str(jvm).encode())
elif tool == "go" and args[0] == "build":
    data = (output / "sources/go/marker.txt").read_bytes()
    failed = (output / "fail-go").exists()
    write(Path(args[args.index("-o") + 1]), data + (b" partial" if failed else b""))
    if failed:
        raise SystemExit(23)
elif tool == "cargo" and args[0] == "build":
    write(output / "rust-driver/Cargo.lock", b"rust lock fixture")
    write(output / "rust-driver/target/debug/interop-driver", b"rust fixture")
elif tool == "pnpm" and "build" in args:
    write(output / "sources/js/packages/library/dist/index.js", b"js fixture")
'''
        for tool in ("gradle", "go", "cargo", "pnpm"):
            path = self.bin / tool
            path.write_text(executable)
            path.chmod(0o755)

    def add_archive(self, language, sha, files):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as package:
            for name, contents in files.items():
                member = tarfile.TarInfo(f"event-store-adapter-{language}-{sha}/{name}")
                member.size = len(contents)
                package.addfile(member, io.BytesIO(contents))
        url = f"https://codeload.github.com/j5ik2o/event-store-adapter-{language}/tar.gz/{sha}"
        self.archives[url] = data.getvalue()

    def record(self, **values):
        path = os.environ.get("INTEROP_TEST_EVIDENCE")
        if path:
            with Path(path).open("a") as stream:
                stream.write(json.dumps(dict(test=self.id(), **values), ensure_ascii=False) + "\n")

    def build(self, only=None):
        argv = ["build.py", "--output", str(self.output), "--gradle", str(self.bin / "gradle"),
                "--java-artifact-directory", str(self.supplied)]
        if only:
            argv += ["--only", only]
        environment = {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"], "INTEROP_TEST_OUTPUT": str(self.output)}
        with mock.patch.object(build, "PINS", self.pins), mock.patch.object(sys, "argv", argv), \
                mock.patch.dict(os.environ, environment), \
                mock.patch.object(build.urllib.request, "urlopen", side_effect=lambda url, **kw: io.BytesIO(self.archives[url])):
            build.main()

    def probe_run(self):
        argv = ["run.py", "--build", str(self.output), "--output", str(self.root / "result")]
        with mock.patch.object(run, "PINS", self.pins), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(run.Local, "start", side_effect=RuntimeError("resource acquisition reached")) as start, \
                mock.patch.object(run.Local, "close", return_value={"errors": []}), mock.patch.object(run, "Driver") as driver, \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                result = {"exit": run.main()}
            except Exception as error:
                result = {"exit": 1, "error": str(error)}
            return dict(result, resource_calls=start.call_count, driver_calls=driver.call_count)

    def test_acquire_refreshes_pin_alias_and_archive(self):
        first, second = "a" * 40, "b" * 40
        for sha in (first, second):
            self.add_archive("go", sha, {"marker.txt": sha.encode()})
        rows = []
        with mock.patch.object(build.urllib.request, "urlopen", side_effect=lambda url, **kw: io.BytesIO(self.archives[url])) as download:
            for sha in (first, second):
                with mock.patch.object(build, "PINS", {"sources": {"go": sha}}):
                    sources = build.acquire(self.output)
                recorded = json.loads((self.output / "source-inputs.json").read_text())[0]
                rows.append({"requested_sha": sha, "recorded": recorded,
                             "actual_bytes": (sources / "go/marker.txt").read_text(),
                             "actual_destination": str((sources / "go").resolve())})
        self.record(acquisitions=rows, downloads=download.call_count)
        for row in rows:
            self.assertEqual(row["actual_bytes"], row["recorded"]["source_sha"])
            self.assertEqual(row["recorded"]["source_sha"], row["requested_sha"])
            self.assertTrue(row["actual_destination"].endswith("event-store-adapter-go-" + row["requested_sha"]))
        self.assertEqual(download.call_count, 2)

    def test_failed_rebuild_invalidates_success_and_blocks_runner(self):
        self.build()
        old_binary = (self.output / "go-driver/driver").read_text()
        (self.output / "fail-go").touch()
        with self.assertRaisesRegex(RuntimeError, "go failed"):
            self.build(only="go")
        result = self.probe_run()
        metadata = {name: (self.output / name).exists() for name in ("drivers.json", "buildinputs.json", "build-failure.json")}
        commands = json.loads((self.output / "build-commands.json").read_text())
        self.record(old_binary=old_binary, actual_binary=(self.output / "go-driver/driver").read_text(),
                    metadata=metadata, failed_exit=commands[-1]["exit"], runner=result)
        self.assertEqual(commands[-1]["exit"], 23)
        self.assertEqual(metadata, {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["resource_calls"], 0)
        self.assertEqual(result["driver_calls"], 0)

    def test_failed_acquisition_invalidates_success_and_blocks_runner(self):
        self.build()
        (self.output / "sources/go/marker.txt").write_text("modified source")
        with self.assertRaisesRegex(RuntimeError, "source archive mismatch"):
            self.build()
        result = self.probe_run()
        metadata = {name: (self.output / name).exists() for name in ("drivers.json", "buildinputs.json", "build-failure.json")}
        self.record(metadata=metadata, runner=result)
        self.assertEqual(metadata, {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
        self.assertEqual(result["resource_calls"], 0)

    def test_runner_rejects_changed_artifact(self):
        self.build()
        (self.output / "go-driver/driver").write_bytes(b"partially updated binary")
        result = self.probe_run()
        self.record(actual_binary=(self.output / "go-driver/driver").read_text(), runner=result)
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["resource_calls"], 0)

    def test_runner_rejects_changed_source_metadata(self):
        self.build()
        path = self.output / "buildinputs.json"
        inputs = json.loads(path.read_text())
        inputs["driver_sources"]["run.py"] = "0" * 64
        build.save(path, inputs)
        result = self.probe_run()
        self.record(recorded_source_sha256=inputs["driver_sources"]["run.py"], runner=result)
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["resource_calls"], 0)

    def test_first_partial_failure_then_full_retry_succeeds(self):
        (self.output / "fail-go").touch()
        with self.assertRaisesRegex(RuntimeError, "go failed"):
            self.build()
        failed_metadata = {name: (self.output / name).exists() for name in ("drivers.json", "buildinputs.json", "build-failure.json")}
        (self.output / "fail-go").unlink()
        self.build()
        inputs = json.loads((self.output / "buildinputs.json").read_text())
        result = self.probe_run()
        self.record(failed_metadata=failed_metadata, artifacts=len(inputs["artifacts"]), retry_runner=result)
        self.assertFalse((self.output / "build-failure.json").exists())
        self.assertEqual(set(json.loads((self.output / "drivers.json").read_text())), set(self.pins["sources"]))
        self.assertEqual(result["resource_calls"], 1)

    def test_only_rebuild_preserves_other_valid_drivers(self):
        self.build()
        previous = json.loads((self.output / "buildinputs.json").read_text())
        self.build(only="go")
        current = json.loads((self.output / "buildinputs.json").read_text())
        result = self.probe_run()
        self.record(previous_artifacts=previous["artifacts"], current_artifacts=current["artifacts"], runner=result)
        self.assertEqual(previous["artifacts"], current["artifacts"])
        self.assertEqual(result["resource_calls"], 1)

    def test_optimized_entries_reject_before_acquisition(self):
        self.build()
        pins = self.root / "pins.json"
        build.save(pins, self.pins)
        for entry in ("build", "run"):
            for mode in ("-O", "PYTHONOPTIMIZE"):
                with self.subTest(entry=entry, mode=mode):
                    trace = self.root / f"{entry}-{mode}-resources.txt"
                    output = self.root / f"{entry}-{mode}-output"
                    code = '''
import importlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
module = importlib.import_module(sys.argv[2])
module.PINS = json.loads(Path(sys.argv[3]).read_text())
trace = Path(sys.argv[4])
def acquisition(*args, **kwargs):
    trace.write_text("resource acquisition reached")
    raise RuntimeError("resource acquisition reached")
if sys.argv[2] == "run":
    module.Local.start = acquisition
    module.Local.close = lambda self: {"errors": []}
else:
    module.urllib.request.urlopen = acquisition
sys.argv = [module.__file__] + sys.argv[5:]
raise SystemExit(module.main())
'''
                    arguments = ["--output", str(output)]
                    if entry == "run":
                        arguments += ["--build", str(self.output)]
                    environment = dict(os.environ)
                    environment.pop("PYTHONOPTIMIZE", None)
                    if mode == "PYTHONOPTIMIZE":
                        environment["PYTHONOPTIMIZE"] = "1"
                    command = [sys.executable] + (["-O"] if mode == "-O" else []) + ["-c", code, str(build.HERE), entry, str(pins), str(trace)] + arguments
                    result = subprocess.run(command, env=environment, capture_output=True, text=True)
                    self.record(entry=entry, mode=mode, subprocess_exit=result.returncode,
                                stdout=result.stdout, stderr=result.stderr, resource_calls=int(trace.exists()))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(trace.exists(), result.stderr)
                    self.assertIn("requires assertions", result.stderr)


if __name__ == "__main__":
    unittest.main()
