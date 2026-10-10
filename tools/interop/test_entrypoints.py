"""取得・ビルド・測定の正規入口で、入力と成功記録の対応を確認する。"""
import contextlib
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
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
        self.probes = 0
        self.pins = copy.deepcopy(build.PINS)
        self.pins["sources"] = {lang: f"{i:040x}" for i, lang in enumerate(self.pins["sources"], 1)}
        self.pins["source_archives"] = {}
        self.archives = {}
        for language, sha in self.pins["sources"].items():
            files = {"marker.txt": sha.encode()}
            if language == "go":
                files.update({"go.mod": b"module github.com/j5ik2o/event-store-adapter-go/v2\n", "go.sum": b""})
            if language == "java":
                files["src/main/java/Fixture.java"] = b"class Fixture {}\n"
            if language == "js":
                files["packages/library/package.json"] = b'{"main":"dist/index.js"}\n'
            self.add_archive(language, sha, files)
            data = self.archives[self.source_url(language)]
            self.pins["source_archives"][language] = {"source_sha": sha, "sha256": hashlib.sha256(data).hexdigest()}
        self.supplied = self.root / "supplied"
        self.supplied.mkdir()
        snapshot = self.pins["java_currentSnapshot"]
        for suffix, key in ((".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")):
            path = self.supplied / (snapshot["artifact"] + suffix)
            with zipfile.ZipFile(path, "w") as package:
                if suffix == "-sources.jar":
                    package.writestr(zipfile.ZipInfo("Fixture.java"), b"class Fixture {}\n")
                else:
                    package.writestr(zipfile.ZipInfo("Fixture.class"), b"fixture bytecode")
            snapshot[key] = build.digest(path)
            self.archives[snapshot["repository"] + path.name] = path.read_bytes()
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
    artifact = next(arg.split("=", 1)[1] for arg in args if arg.startswith("-PjavaArtifact="))
    write(jvm / "classes/main/Fixture.class", b"jvm fixture")
    write(jvm / "classes/main/META-INF/fixture.module", b"runtime metadata")
    write(jvm / "classpath.txt", os.pathsep.join([str(jvm / "classes/main"),
        str(jvm / "resources/main"), artifact]).encode())
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
    library = output / "sources/js/packages/library"
    write(library / "dist/index.js", b"module.exports = {fixtureMarker: require('fixture-dependency')};\\n")
    write(library / "dist/alternate.js", b"module.exports = {fixtureMarker: 'alternate entry'};\\n")
    dependency = output / "sources/js/node_modules/fixture-dependency"
    write(dependency / "package.json", b'{"main":"index.js"}\\n')
    write(dependency / "index.js", b"module.exports = 'original dependency';\\n")
    write(dependency / "unused.js", b"module.exports = 'unused dependency';\\n")
    link = library / "node_modules/fixture-dependency"
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(dependency, target_is_directory=True)
    write(library / "node_modules/@aws-sdk/client-dynamodb/package.json", b'{"main":"index.js"}\\n')
    write(library / "node_modules/@aws-sdk/client-dynamodb/index.js", b"exports.DynamoDBClient = class { destroy() {} };\\n")
'''
        for tool in ("gradle", "go", "cargo", "pnpm"):
            path = self.bin / tool
            path.write_text(executable)
            path.chmod(0o755)

    def add_archive(self, language, sha, files):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as package:
            for name, contents in files.items():
                member = tarfile.TarInfo(f"event-store-adapter-{language}-{sha}/{name}")
                member.size = len(contents)
                package.addfile(member, io.BytesIO(contents))
        url = f"https://codeload.github.com/j5ik2o/event-store-adapter-{language}/tar.gz/{sha}"
        self.archives[url] = gzip.compress(data.getvalue(), mtime=0)

    def source_url(self, language):
        return f"https://codeload.github.com/j5ik2o/event-store-adapter-{language}/tar.gz/{self.pins['sources'][language]}"

    def metadata(self):
        return {name: (self.output / name).exists() for name in ("drivers.json", "buildinputs.json", "build-failure.json")}

    def file_state(self, path):
        if not path.exists():
            return {"exists": False}
        data = path.read_bytes()
        return {"exists": True, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "prefix_hex": data[:24].hex()}

    def attempt(self, **kwargs):
        try:
            self.build(**kwargs)
            result = {"accepted": True}
        except Exception as error:
            result = {"accepted": False, "error": str(error)}
        return dict(result, downloads=list(self.downloads), metadata=self.metadata(), runner=self.probe_run())

    def record(self, **values):
        path = os.environ.get("INTEROP_TEST_EVIDENCE")
        if path:
            with Path(path).open("a") as stream:
                stream.write(json.dumps(dict(test=self.id(), **values), ensure_ascii=False) + "\n")

    def build(self, only=None, *, supplied=True):
        argv = ["build.py", "--output", str(self.output), "--gradle", str(self.bin / "gradle")]
        if supplied:
            argv += ["--java-artifact-directory", str(self.supplied)]
        if only:
            argv += ["--only", only]
        environment = {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"], "INTEROP_TEST_OUTPUT": str(self.output)}
        self.downloads = []

        def fetch(url, **kwargs):
            data = self.archives[url]
            self.downloads.append({"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            return io.BytesIO(data)

        with mock.patch.object(build, "PINS", self.pins), mock.patch.object(sys, "argv", argv), \
                mock.patch.dict(os.environ, environment), \
                mock.patch.object(build.urllib.request, "urlopen", side_effect=fetch) as download:
            build.main()
            return download.call_count

    def probe_run(self):
        self.probes += 1
        argv = ["run.py", "--build", str(self.output), "--output", str(self.root / f"result-{self.probes}")]
        with mock.patch.object(run, "PINS", self.pins), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(run.Local, "start", side_effect=RuntimeError("resource acquisition reached")) as start, \
                mock.patch.object(run.Local, "close", return_value={"errors": []}), mock.patch.object(run, "Driver") as driver, \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                result = {"exit": run.main()}
            except Exception as error:
                result = {"exit": 1, "error": str(error)}
            return dict(result, resource_calls=start.call_count, driver_calls=driver.call_count)

    @contextlib.contextmanager
    def copied_entrypoints(self):
        here = self.root / "entrypoints"
        shutil.copytree(build.HERE, here, ignore=shutil.ignore_patterns("__pycache__"))
        with mock.patch.object(build, "HERE", here), mock.patch.object(run, "HERE", here):
            yield here

    def js_value(self):
        library = self.output / "sources/js/packages/library"
        result = subprocess.run(["node", "-e", """
const { createRequire } = require('node:module');
const library = process.argv[1];
const local = createRequire(library + '/package.json');
console.log(JSON.stringify({value: local(library).fixtureMarker,
    dependency: local.resolve('fixture-dependency')}));
""", str(library)], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_acquire_retries_interrupted_extraction(self):
        original = tarfile.TarFile.extractall

        def interrupted(package, path=".", **kwargs):
            original(package, path, members=package.getmembers()[:1], **kwargs)
            raise RuntimeError("fixture extraction interrupted")

        with mock.patch.object(tarfile.TarFile, "extractall", new=interrupted):
            with self.assertRaisesRegex(RuntimeError, "fixture extraction interrupted"):
                self.build()
        failure = json.loads((self.output / "build-failure.json").read_text())
        language = next(iter(self.pins["sources"]))
        destination = self.output / "sources" / f"event-store-adapter-{language}-{self.pins['sources'][language]}"
        incomplete_destination = destination.exists()
        try:
            downloads = self.build()
            retry = {"accepted": True, "downloads": downloads, "runner": self.probe_run()}
        except Exception as error:
            retry = {"accepted": False, "error": str(error)}
        self.record(first_failure=failure, incomplete_destination=incomplete_destination, retry=retry)
        self.assertFalse(incomplete_destination)
        self.assertTrue(retry["accepted"], retry)
        self.assertEqual(retry["runner"]["resource_calls"], 1)
        self.assertFalse((self.output / "build-failure.json").exists())

    def test_acquire_retries_incomplete_download(self):
        language = next(iter(self.pins["sources"]))
        url = f"https://codeload.github.com/j5ik2o/event-store-adapter-{language}/tar.gz/{self.pins['sources'][language]}"
        complete = self.archives[url]
        self.archives[url] = complete[:12]
        with self.assertRaises(Exception):
            self.build()
        first_failure = json.loads((self.output / "build-failure.json").read_text())
        incomplete_archive = (self.output / f"sources/{language}.tar.gz").exists()
        self.archives[url] = complete
        try:
            self.build()
            retry = {"accepted": True, "runner": self.probe_run()}
        except Exception as error:
            retry = {"accepted": False, "error": str(error)}
        self.record(first_failure=first_failure, incomplete_archive=incomplete_archive, retry=retry)
        self.assertFalse(incomplete_archive)
        self.assertTrue(retry["accepted"], retry)
        self.assertEqual(retry["runner"]["resource_calls"], 1)

    def test_acquire_recovers_cached_missing_files_without_download(self):
        self.build()
        for language in ("js", "go"):
            (self.output / f"sources/{language}/marker.txt").unlink()
        try:
            downloads = self.build()
            recovery = {"accepted": True, "downloads": downloads, "runner": self.probe_run()}
        except Exception as error:
            recovery = {"accepted": False, "error": str(error)}
        report = self.output / "source-recovery.jsonl"
        self.record(recovery=recovery, reports=[json.loads(line) for line in report.read_text().splitlines()] if report.exists() else [])
        self.assertTrue(recovery["accepted"], recovery)
        self.assertEqual(recovery["downloads"], 0)
        self.assertEqual(recovery["runner"]["resource_calls"], 1)
        for language in ("js", "go"):
            self.assertEqual((self.output / f"sources/{language}/marker.txt").read_text(), self.pins["sources"][language])
        self.assertTrue(report.exists())

    def test_acquire_recovers_cached_incomplete_archive(self):
        sources = self.output / "sources"
        sources.mkdir()
        (sources / "go.tar.gz").write_bytes(b"incomplete cached archive")
        try:
            self.build()
            recovery = {"accepted": True, "runner": self.probe_run()}
        except Exception as error:
            recovery = {"accepted": False, "error": str(error)}
        self.record(recovery=recovery)
        self.assertTrue(recovery["accepted"], recovery)
        self.assertEqual(recovery["runner"]["resource_calls"], 1)

    def test_acquire_rejects_partial_cache_with_added_or_changed_files(self):
        for mode in ("added", "changed"):
            with self.subTest(mode=mode):
                self.build()
                missing = self.output / "sources/go/go.sum"
                original_missing = missing.read_bytes()
                missing.unlink()
                changed = self.output / ("sources/go/extra.go" if mode == "added" else "sources/go/marker.txt")
                original_changed = changed.read_bytes() if changed.exists() else None
                changed.write_bytes(b"untrusted source")
                with self.assertRaisesRegex(RuntimeError, "source archive mismatch"):
                    self.build()
                result = self.probe_run()
                self.record(mode=mode, runner=result, cache_retained=changed.read_bytes() == b"untrusted source")
                self.assertEqual(result["resource_calls"], 0)
                self.assertEqual(changed.read_bytes(), b"untrusted source")
                missing.write_bytes(original_missing)
                if original_changed is None:
                    changed.unlink()
                else:
                    changed.write_bytes(original_changed)

    def test_runner_rejects_added_jvm_shadow_class(self):
        source = self.root / "Shadow.java"
        dependency = self.root / "dependency"
        source.write_text('package fixture; public class Shadow { public static void main(String[] args) { System.out.print("original dependency"); } }')
        subprocess.run(["javac", "-d", str(dependency), str(source)], capture_output=True, text=True, check=True)
        snapshot = self.pins["java_currentSnapshot"]
        jar = self.supplied / (snapshot["artifact"] + ".jar")
        with zipfile.ZipFile(jar, "w") as package:
            package.write(dependency / "fixture/Shadow.class", "fixture/Shadow.class")
        snapshot["jar_sha256"] = build.digest(jar)
        self.build()
        baseline = self.probe_run()
        classpath = (self.output / "jvm/classpath.txt").read_text()
        command = ["java", "-cp", classpath, "fixture.Shadow"]
        before = subprocess.run(command, capture_output=True, text=True, check=True).stdout
        source.write_text('package fixture; public class Shadow { public static void main(String[] args) { System.out.print("unrecorded shadow class"); } }')
        classes = Path(classpath.split(os.pathsep)[0])
        subprocess.run(["javac", "-d", str(classes), str(source)], capture_output=True, text=True, check=True)
        after = subprocess.run(command, capture_output=True, text=True, check=True).stdout
        result = self.probe_run()
        self.record(before=baseline, before_java=before, after_java=after, after=result,
                    added_class=str(classes / "fixture/Shadow.class"))
        self.assertEqual(before, "original dependency")
        self.assertEqual(after, "unrecorded shadow class")
        self.assertEqual(baseline["resource_calls"], 1)
        self.assertEqual(result["resource_calls"], 0)
        self.assertEqual(result["driver_calls"], 0)

    def test_full_rebuild_removes_preexisting_jvm_shadow_and_resources(self):
        source = self.root / "Shadow.java"
        dependency = self.root / "dependency"
        source.write_text('package fixture; public class Shadow { public static void main(String[] args) { System.out.print("original dependency"); } }')
        subprocess.run(["javac", "-d", str(dependency), str(source)], capture_output=True, text=True, check=True)
        snapshot = self.pins["java_currentSnapshot"]
        jar = self.supplied / (snapshot["artifact"] + ".jar")
        with zipfile.ZipFile(jar, "w") as package:
            package.write(dependency / "fixture/Shadow.class", "fixture/Shadow.class")
        snapshot["jar_sha256"] = build.digest(jar)
        self.build()
        classpath = (self.output / "jvm/classpath.txt").read_text()
        classes, resources = map(Path, classpath.split(os.pathsep)[:2])
        source.write_text('package fixture; public class Shadow { public static void main(String[] args) { System.out.print("unrecorded shadow class"); } }')
        subprocess.run(["javac", "-d", str(classes), str(source)], capture_output=True, text=True, check=True)
        resource = resources / "extra.properties"
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("unrecorded resource")
        preserved = [self.output / "gradle-cache/keep", self.output / "jvm/user-resource"]
        for path in preserved:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("user input")
        before = subprocess.run(["java", "-cp", classpath, "fixture.Shadow"], capture_output=True, text=True, check=True).stdout
        self.build()
        after = subprocess.run(["java", "-cp", classpath, "fixture.Shadow"], capture_output=True, text=True, check=True).stdout
        runner = self.probe_run()
        self.record(before_java=before, after_java=after, resource_exists=resource.exists(), runner=runner,
                    preserved={str(path): path.read_text() for path in preserved})
        self.assertEqual(before, "unrecorded shadow class")
        self.assertEqual(after, "original dependency")
        self.assertFalse(resource.exists())
        self.assertTrue(all(path.read_text() == "user input" for path in preserved))
        self.assertEqual(runner["resource_calls"], 1)

    def test_generated_go_package_rejects_extra_compilation_inputs(self):
        for only, name in ((None, "extra.go"), ("go", "extra.s"), ("go", "nested/extra.go")):
            with self.subTest(only=only, name=name):
                self.build()
                path = self.output / "go-driver" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unrecorded compilation input")
                previous_calls = (self.output / "tool-calls.jsonl").read_bytes()
                previous = build.source_inventory(self.output, "go")
                attempt = self.attempt(only=only)
                current = build.source_inventory(self.output, "go")
                preserved = {key: value for key, value in previous.items()
                             if key not in {"drivers.json", "buildinputs.json", "build-failure.json"}}
                self.record(input=name, only=only, attempt=attempt,
                            compiler_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == previous_calls,
                            previous_inputs_preserved=all(current.get(key) == value for key, value in preserved.items()))
                self.assertFalse(attempt["accepted"], attempt)
                self.assertIn("unexpected generated package input", attempt["error"])
                self.assertEqual(attempt["downloads"], [])
                self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), previous_calls)
                self.assertTrue(all(current.get(key) == value for key, value in preserved.items()))
                self.assertEqual(attempt["runner"]["resource_calls"], 0)
                path.unlink()
                if path.parent != self.output / "go-driver":
                    path.parent.rmdir()

    def test_generated_rust_package_rejects_automatic_inputs(self):
        for name in ("build.rs", "src/lib.rs", "src/bin/extra.rs", "examples/extra.rs",
                     "tests/extra.rs", "benches/extra.rs", ".cargo/config.toml"):
            with self.subTest(input=name):
                self.build()
                path = self.output / "rust-driver" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unrecorded package input")
                previous_calls = (self.output / "tool-calls.jsonl").read_bytes()
                previous = build.source_inventory(self.output, "go")
                attempt = self.attempt(only="rust")
                current = build.source_inventory(self.output, "go")
                preserved = {key: value for key, value in previous.items()
                             if key not in {"drivers.json", "buildinputs.json", "build-failure.json"}}
                self.record(input=name, attempt=attempt,
                            compiler_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == previous_calls,
                            previous_inputs_preserved=all(current.get(key) == value for key, value in preserved.items()))
                self.assertFalse(attempt["accepted"], attempt)
                self.assertIn("unexpected generated package input", attempt["error"])
                self.assertEqual(attempt["downloads"], [])
                self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), previous_calls)
                self.assertTrue(all(current.get(key) == value for key, value in preserved.items()))
                self.assertEqual(attempt["runner"]["resource_calls"], 0)
                path.unlink()
                if path.parent != self.output / "rust-driver/src" and path.parent != self.output / "rust-driver":
                    path.parent.rmdir()

    def test_generated_package_symlinks_preserve_other_owner(self):
        for name in ("go-driver", "rust-driver", "rust-driver/src", "go-driver/main.go"):
            with self.subTest(input=name):
                self.build()
                path = self.output / name
                saved = self.root / ("saved-" + name.replace("/", "-"))
                path.rename(saved)
                foreign = self.root / "other-owner"
                foreign.mkdir(exist_ok=True)
                (foreign / "keep").write_text("other owner's resource")
                target = foreign / "main.go" if name.endswith("main.go") else foreign
                if name.endswith("main.go"):
                    target.write_text("other owner's source")
                path.symlink_to(target, target_is_directory=not name.endswith("main.go"))
                previous = build.source_inventory(foreign, "go")
                calls = (self.output / "tool-calls.jsonl").read_bytes()
                try:
                    attempt = self.attempt()
                    current = build.source_inventory(foreign, "go")
                    link_preserved = path.is_symlink()
                    calls_unchanged = (self.output / "tool-calls.jsonl").read_bytes() == calls
                    self.record(input=name, attempt=attempt, foreign_before=previous, foreign_after=current,
                                link_preserved=link_preserved, compiler_calls_unchanged=calls_unchanged)
                finally:
                    path.unlink()
                    saved.rename(path)
                self.assertFalse(attempt["accepted"], attempt)
                self.assertIn("generated package", attempt["error"])
                self.assertEqual(current, previous)
                self.assertTrue(link_preserved)
                self.assertTrue(calls_unchanged)
                self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_build_rejects_output_resolving_inside_source_before_side_effects(self):
        with self.copied_entrypoints() as here:
            alias = self.root / "source-alias"
            alias.symlink_to(here, target_is_directory=True)
            for output in (here, here / "generated-build", alias / "generated-build"):
                with self.subTest(output=str(output)):
                    self.output = output
                    previous = build.source_inventory(here, "go")
                    with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire, \
                            mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as compiler:
                        try:
                            self.build()
                            attempt = {"accepted": True}
                        except Exception as error:
                            attempt = {"accepted": False, "error": str(error)}
                    current = build.source_inventory(here, "go")
                    self.record(output=str(output), attempt=attempt, acquisition_calls=acquire.call_count,
                                subprocess_calls=compiler.call_count, downloads=self.downloads,
                                source_unchanged=current == previous)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("output must be outside tools/interop", attempt["error"])
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual(compiler.call_count, 0)
                    self.assertEqual(self.downloads, [])
                    self.assertEqual(current, previous)

    def test_run_rejects_output_resolving_inside_source_before_side_effects(self):
        with self.copied_entrypoints() as here:
            self.build()
            alias = self.root / "source-alias"
            alias.symlink_to(here, target_is_directory=True)
            for output in (here, here / "generated-result", alias / "generated-result"):
                with self.subTest(output=str(output)):
                    previous = build.source_inventory(here, "go")
                    argv = ["run.py", "--build", str(self.output), "--output", str(output)]
                    with mock.patch.object(sys, "argv", argv), mock.patch.object(run, "PINS", self.pins), \
                            mock.patch.object(run, "verify_artifacts", wraps=run.verify_artifacts) as verify, \
                            mock.patch.object(run.Local, "start", side_effect=RuntimeError("resource acquisition reached")) as start, \
                            mock.patch.object(run.Local, "close", return_value={"errors": []}), \
                            mock.patch.object(run, "Driver") as driver, contextlib.redirect_stdout(io.StringIO()):
                        try:
                            attempt = {"accepted": True, "exit": run.main()}
                        except Exception as error:
                            attempt = {"accepted": False, "error": str(error)}
                    current = build.source_inventory(here, "go")
                    self.record(output=str(output), attempt=attempt, artifact_verification_calls=verify.call_count,
                                resource_calls=start.call_count, driver_calls=driver.call_count,
                                source_unchanged=current == previous)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("output must be outside tools/interop", attempt["error"])
                    self.assertEqual(verify.call_count, 0)
                    self.assertEqual(start.call_count, 0)
                    self.assertEqual(driver.call_count, 0)
                    self.assertEqual(current, previous)

    def test_outputs_resolving_outside_source_remain_usable(self):
        with self.copied_entrypoints() as here:
            self.output = here / "external-build"
            self.output.symlink_to(self.root / "external-build", target_is_directory=True)
            output = here / "external-result"
            output.symlink_to(self.root / "external-result", target_is_directory=True)
            previous = build.source_inventory(here, "go")
            self.build()
            argv = ["run.py", "--build", str(self.output), "--output", str(output)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(run, "PINS", self.pins), \
                    mock.patch.object(run.Local, "start", side_effect=RuntimeError("resource acquisition reached")) as start, \
                    mock.patch.object(run.Local, "close", return_value={"errors": []}), contextlib.redirect_stdout(io.StringIO()):
                exit = run.main()
            current = build.source_inventory(here, "go")
            self.record(build_path=str(self.output), build_resolved=str(self.output.resolve()),
                        result_path=str(output), result_resolved=str(output.resolve()), exit=exit,
                        resource_calls=start.call_count, source_unchanged=current == previous)
            self.assertEqual(start.call_count, 1)
            self.assertTrue(output.exists())
            self.assertEqual(current, previous)

    def test_invalid_cached_json_invalidates_success_and_records_failure(self):
        for name in ("build-commands.json", "buildinputs.json"):
            for contents in ('[{"label":', 'not JSON'):
                with self.subTest(name=name, contents=contents):
                    (self.output / "build-commands.json").unlink(missing_ok=True)
                    (self.output / "buildinputs.json").unlink(missing_ok=True)
                    self.build()
                    (self.output / name).write_text(contents)
                    before_tools = (self.output / "tool-calls.jsonl").read_text()
                    attempt = self.attempt()
                    failure_path = self.output / "build-failure.json"
                    failure = json.loads(failure_path.read_text()) if failure_path.exists() else None
                    self.record(name=name, contents=contents, attempt=attempt, failure=failure)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
                    self.assertIsNotNone(failure)
                    self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    self.assertEqual(attempt["runner"]["driver_calls"], 0)
                    self.assertEqual((self.output / "tool-calls.jsonl").read_text(), before_tools)
                    (self.output / name).unlink(missing_ok=True)
                    self.build()
                    self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_node_preload_is_excluded_from_build_verify_and_driver(self):
        hook = self.root / "hook.cjs"
        marker = self.root / "hook-marker.jsonl"
        hook.write_text("require('node:fs').appendFileSync(" + json.dumps(str(marker))
                        + ", JSON.stringify({argv: process.argv}) + '\\n');\n")
        preload = {"NODE_OPTIONS": "--require=" + str(hook)}
        with mock.patch.dict(os.environ, preload):
            self.build()
            build.verify_artifacts(json.loads((self.output / "buildinputs.json").read_text()))
            probe = self.root / "probe.mjs"
            probe.write_text('for await (const line of process.stdin) {}\n')
            driver = run.Driver("js", {"argv": ["node", str(probe)], "env": {}}, self.root, None)
            exit = driver.close()
            parent_unchanged = os.environ["NODE_OPTIONS"] == preload["NODE_OPTIONS"]
        rows = [json.loads(line) for line in marker.read_text().splitlines()] if marker.exists() else []
        self.record(hook_executions=rows, driver_exit=exit, parent_unchanged=parent_unchanged)
        self.assertEqual(exit["exit"], 0)
        self.assertTrue(parent_unchanged)
        self.assertEqual(rows, [])

    def test_jvm_native_and_explicit_driver_preloads_are_excluded(self):
        preload = {key: "unrecorded preload" for key in (
            "NODE_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS",
            "JAVA_OPTS", "GRADLE_OPTS", "LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES")}
        for language, command in (("java", ["java", "-version"]), ("go", ["go-driver"]), ("rs", ["rust-driver"])):
            with self.subTest(language=language), mock.patch.dict(os.environ, dict(preload, JAVA_HOME="kept-java-home")), \
                    mock.patch.object(run.subprocess, "Popen") as popen:
                popen.return_value.stdout = io.StringIO("")
                popen.return_value.wait.return_value = 0
                definition = {"argv": command, "env": dict(preload, INTEROP_EXPLICIT_INPUT="kept-input")}
                driver = run.Driver(language, definition, self.root, None)
                child = popen.call_args.kwargs["env"]
                driver.close()
                self.record(language=language, child_preload_keys=sorted(preload.keys() & child.keys()),
                            path_preserved=child["PATH"] == os.environ["PATH"], java_home=child["JAVA_HOME"],
                            explicit_input=child["INTEROP_EXPLICIT_INPUT"], parent_unchanged=all(os.environ[k] == v for k, v in preload.items()))
                self.assertFalse(preload.keys() & child.keys())
                self.assertEqual(child["PATH"], os.environ["PATH"])
                self.assertEqual(child["JAVA_HOME"], "kept-java-home")
                self.assertEqual(child["INTEROP_EXPLICIT_INPUT"], "kept-input")
                self.assertTrue(all(os.environ[k] == v for k, v in preload.items()))

    def test_duplicate_validator_rejects_changed_head_binary_at_same_sequence(self):
        before = {"aid": {"S": "Interop-shared"}, "type_name": {"S": "Interop"}, "seq_nr": {"N": "6"},
                  "events": {"L": [{"M": {"seq_nr": {"N": "6"}, "occurred_at": {"N": str(run.BASE_NS)},
                    "manifest": {"S": "interop-event/v1"}, "payload": {"B": b'{"value":"original"}'}}}]}}
        reply = {"status": "error", "category": "optimisticLock"}
        run.validate_duplicate(reply, before, copy.deepcopy(before))
        after = copy.deepcopy(before)
        after["events"]["L"][0]["M"]["payload"]["B"] = b'{"value":"changed"}'
        with self.assertRaises(AssertionError):
            run.validate_duplicate(reply, before, after)
        self.record(head_before=json.loads(json.dumps(before, default=run.evidence)),
                    head_after=json.loads(json.dumps(after, default=run.evidence)),
                    same_sequence=before["seq_nr"] == after["seq_nr"], changed_binary_rejected=True)

    def test_runner_rejects_redirected_or_missing_jvm_class_directory(self):
        for mode in ("redirected", "missing"):
            with self.subTest(mode=mode):
                self.build()
                baseline = self.probe_run()
                classes = Path((self.output / "jvm/classpath.txt").read_text().split(os.pathsep)[0])
                backup = self.root / f"{mode}-classes"
                classes.rename(backup)
                if mode == "redirected":
                    classes.symlink_to(backup, target_is_directory=True)
                result = self.probe_run()
                self.record(mode=mode, before=baseline, after=result, same_bytes=mode == "redirected")
                if classes.is_symlink():
                    classes.unlink()
                backup.rename(classes)
                self.assertEqual(baseline["resource_calls"], 1)
                self.assertEqual(result["resource_calls"], 0)
                self.assertEqual(result["driver_calls"], 0)

    def test_runner_rejects_changed_or_added_jvm_resources(self):
        for mode in ("changed", "missing", "added", "created-directory"):
            with self.subTest(mode=mode):
                self.build()
                baseline = self.probe_run()
                entries = (self.output / "jvm/classpath.txt").read_text().split(os.pathsep)
                path = Path(entries[1]) / "fixture.properties" if mode == "created-directory" else Path(entries[0]) / "META-INF/fixture.module"
                if mode == "added":
                    path = path.with_name("extra.properties")
                original = path.read_bytes() if path.exists() else None
                if mode == "missing":
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"unrecorded runtime resource")
                result = self.probe_run()
                self.record(mode=mode, before=baseline, after=result, path=str(path))
                if original is None:
                    path.unlink()
                    if mode == "created-directory":
                        path.parent.rmdir()
                else:
                    path.write_bytes(original)
                self.assertEqual(baseline["resource_calls"], 1)
                self.assertEqual(result["resource_calls"], 0)
                self.assertEqual(result["driver_calls"], 0)

    def test_only_rejects_unrecorded_unselected_jvm_inputs(self):
        self.build()
        classes = Path((self.output / "jvm/classpath.txt").read_text().split(os.pathsep)[0])
        (classes / "Added.class").write_bytes(b"unrecorded bytecode")
        before = (self.output / "tool-calls.jsonl").read_text()
        try:
            self.build(only="go")
            outcome = {"accepted": True}
        except RuntimeError as error:
            outcome = {"accepted": False, "error": str(error)}
        result = self.probe_run()
        self.record(build=outcome, runner=result)
        self.assertFalse(outcome["accepted"], outcome)
        self.assertEqual((self.output / "tool-calls.jsonl").read_text(), before)
        self.assertEqual(result["resource_calls"], 0)

    def test_acquire_rejects_added_build_sources(self):
        for language, name in (("go", "extra.go"), ("rs", "lib/src/extra.rs"),
                               ("js", "packages/library/src/extra.ts")):
            with self.subTest(language=language):
                pins = {"sources": {language: self.pins["sources"][language]},
                        "source_archives": {language: self.pins["source_archives"][language]}}
                with mock.patch.object(build, "PINS", pins), \
                        mock.patch.object(build.urllib.request, "urlopen", side_effect=lambda url, **kw: io.BytesIO(self.archives[url])):
                    sources = build.acquire(self.output)
                    added = sources / language / name
                    added.parent.mkdir(parents=True, exist_ok=True)
                    added.write_text("additional build source\n")
                    try:
                        build.acquire(self.output)
                        outcome = {"accepted": True}
                    except RuntimeError as error:
                        outcome = {"accepted": False, "error": str(error)}
                self.record(language=language, added_file=name, acquisition=outcome)
                self.assertFalse(outcome["accepted"], outcome)
                self.assertIn(name, outcome["error"])

    def test_acquire_preserves_known_js_generated_directories(self):
        self.build()
        sources = self.output / "sources"
        for name in ("node_modules/cache.js", "packages/library/dist/extra.js",
                     "packages/examples/node_modules/cache.js", "packages/tests/node_modules/cache.js"):
            path = sources / "js" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated fixture\n")
        before = json.loads((self.output / "source-inputs.json").read_text())
        self.build()
        after = json.loads((self.output / "source-inputs.json").read_text())
        self.record(before=before, after=after, runner=self.probe_run())
        self.assertEqual(before, after)
        self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_acquire_rejects_replaced_source_file_symlink(self):
        self.build()
        path = self.output / "sources/go/marker.txt"
        original = path.read_bytes()
        redirected = self.root / "outside-marker.txt"
        redirected.write_bytes(original)
        path.unlink()
        path.symlink_to(redirected)
        try:
            self.build()
            outcome = {"accepted": True}
        except RuntimeError as error:
            outcome = {"accepted": False, "error": str(error)}
        self.record(acquisition=outcome, same_bytes=path.read_bytes() == original, target=str(path.resolve()))
        self.assertFalse(outcome["accepted"], outcome)

    def test_runner_rejects_changed_source_alias(self):
        self.build()
        baseline = self.probe_run()
        alias = self.output / "sources/js"
        old = alias.resolve()
        alias.unlink()
        alias.symlink_to(self.output / "sources/go", target_is_directory=True)
        result = self.probe_run()
        self.record(before=baseline, after=result, old_target=str(old), actual_target=str(alias.resolve()))
        self.assertEqual(baseline["resource_calls"], 1)
        self.assertEqual(result["resource_calls"], 0)
        self.assertEqual(result["driver_calls"], 0)

    def test_runner_rejects_changed_js_package_main(self):
        self.build()
        baseline = self.probe_run()
        before = self.js_value()
        path = self.output / "sources/js/packages/library/package.json"
        path.write_text('{"main":"dist/alternate.js"}\n')
        after = self.js_value()
        result = self.probe_run()
        self.record(before=baseline, before_require=before, after_require=after, after=result)
        self.assertEqual(baseline["resource_calls"], 1)
        self.assertNotEqual(before["value"], after["value"])
        self.assertEqual(result["resource_calls"], 0)
        self.assertEqual(result["driver_calls"], 0)

    def test_runner_rejects_changed_js_dependency_bytes(self):
        self.build()
        baseline = self.probe_run()
        before = self.js_value()
        path = Path(before["dependency"])
        path.write_text("module.exports = 'changed dependency';\n")
        after = self.js_value()
        result = self.probe_run()
        self.record(before=baseline, before_require=before, after_require=after, after=result)
        self.assertEqual(baseline["resource_calls"], 1)
        self.assertNotEqual(before["value"], after["value"])
        self.assertEqual(result["resource_calls"], 0)
        self.assertEqual(result["driver_calls"], 0)

    def test_runner_rejects_redirected_js_dependency(self):
        self.build()
        baseline = self.probe_run()
        before = self.js_value()
        library = self.output / "sources/js/packages/library"
        alternative = library / "node_modules/alternative-dependency"
        alternative.mkdir()
        for name in ("package.json", "index.js"):
            (alternative / name).write_bytes((Path(before["dependency"]).parent / name).read_bytes())
        link = library / "node_modules/fixture-dependency"
        link.unlink()
        link.symlink_to(alternative, target_is_directory=True)
        after = self.js_value()
        result = self.probe_run()
        self.record(before=baseline, before_require=before, after_require=after, after=result)
        self.assertEqual(baseline["resource_calls"], 1)
        self.assertEqual(before["value"], after["value"])
        self.assertNotEqual(before["dependency"], after["dependency"])
        self.assertEqual(result["resource_calls"], 0)

    def test_runner_ignores_unused_js_dependency_files(self):
        self.build()
        unused = self.output / "sources/js/node_modules/fixture-dependency/unused.js"
        unused.write_text("module.exports = 'changed unused dependency';\n")
        inputs = json.loads((self.output / "buildinputs.json").read_text())
        result = self.probe_run()
        self.record(unused_path=str(unused), runner=result)
        self.assertNotIn(str(unused.resolve()), {row["path"] for row in inputs["artifacts"]})
        self.assertEqual(result["resource_calls"], 1)

    def test_only_rejects_changed_unselected_js_runtime(self):
        for name in ("node_modules/fixture-dependency/index.js", "packages/library/package.json"):
            with self.subTest(input=name):
                self.build()
                path = self.output / "sources/js" / name
                path.write_bytes(path.read_bytes() + b" \n")
                calls = (self.output / "tool-calls.jsonl").read_text().splitlines()
                try:
                    self.build(only="go")
                    outcome = {"accepted": True}
                except RuntimeError as error:
                    outcome = {"accepted": False, "error": str(error)}
                result = self.probe_run()
                current_calls = (self.output / "tool-calls.jsonl").read_text().splitlines()
                metadata = {key: (self.output / key).exists() for key in ("drivers.json", "buildinputs.json", "build-failure.json")}
                self.record(changed_input=name, build=outcome, tools_before=len(calls), tools_after=len(current_calls),
                            metadata=metadata, runner=result)
                self.assertFalse(outcome["accepted"], outcome)
                self.assertEqual(calls, current_calls)
                self.assertEqual(metadata, {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
                self.assertEqual(result["resource_calls"], 0)

    def test_acquire_refreshes_pin_alias_and_archive(self):
        first, second = "a" * 40, "b" * 40
        for sha in (first, second):
            self.add_archive("go", sha, {"marker.txt": sha.encode()})
        rows = []
        with mock.patch.object(build.urllib.request, "urlopen", side_effect=lambda url, **kw: io.BytesIO(self.archives[url])) as download:
            for sha in (first, second):
                archive_pin = {"source_sha": sha, "sha256": hashlib.sha256(self.archives[
                    f"https://codeload.github.com/j5ik2o/event-store-adapter-go/tar.gz/{sha}"]).hexdigest()}
                with mock.patch.object(build, "PINS", {"sources": {"go": sha}, "source_archives": {"go": archive_pin}}):
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

    def test_only_rejects_changed_shared_build_then_full_retry_succeeds(self):
        with self.copied_entrypoints() as here:
            self.build()
            previous = json.loads((self.output / "buildinputs.json").read_text())
            shared = here / "build.py"
            original = shared.read_text()
            changed = original.replace('serde_json = "1.0"',
                'serde_json = {{ version = "1.0", features = ["preserve_order"] }}')
            self.assertNotEqual(changed, original)
            shared.write_text(changed)
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            result = self.attempt(only="js")
            self.record(previous_shared_sha256=previous["driver_sources"]["build.py"],
                        current_shared_sha256=build.digest(shared), partial=result,
                        compiler_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == calls)
            self.assertFalse(result["accepted"], result)
            self.assertIn("shared build input changed", result["error"])
            self.assertEqual(result["downloads"], [])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(result["metadata"], {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
            self.assertEqual(result["runner"]["resource_calls"], 0)
            self.assertEqual(result["runner"]["driver_calls"], 0)
            self.build()
            current = json.loads((self.output / "buildinputs.json").read_text())
            retry = self.probe_run()
            self.record(full_retry=retry, recorded_shared_sha256=current["driver_sources"]["build.py"])
            self.assertEqual(current["driver_sources"]["build.py"], build.digest(shared))
            self.assertFalse(self.metadata()["build-failure.json"])
            self.assertEqual(retry["resource_calls"], 1)

    def test_only_accepts_changed_selected_driver_with_unchanged_shared_build(self):
        with self.copied_entrypoints() as here:
            self.build()
            previous = json.loads((self.output / "buildinputs.json").read_text())
            selected = here / "drivers/go/main.go"
            selected.write_text(selected.read_text() + "\n// 選択したドライバーの変更\n")
            result = self.attempt(only="go")
            current = json.loads((self.output / "buildinputs.json").read_text())
            self.record(partial=result, previous_sources=previous["driver_sources"], current_sources=current["driver_sources"])
            self.assertTrue(result["accepted"], result)
            self.assertEqual(current["driver_sources"]["build.py"], previous["driver_sources"]["build.py"])
            self.assertNotEqual(current["driver_sources"]["drivers/go/main.go"], previous["driver_sources"]["drivers/go/main.go"])
            self.assertEqual((self.output / "go-driver/main.go").read_bytes(), selected.read_bytes())
            self.assertEqual(previous["artifacts"], current["artifacts"])
            self.assertEqual(result["runner"]["resource_calls"], 1)

    def test_only_rejects_changed_unselected_driver_sources(self):
        with self.copied_entrypoints() as here:
            self.build()
            unselected = here / "drivers/rust/main.rs"
            unselected.write_text(unselected.read_text() + "\n// 未選択ドライバーの変更\n")
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            result = self.attempt(only="js")
            self.record(partial=result, compiler_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == calls)
            self.assertFalse(result["accepted"], result)
            self.assertIn("unselected driver sources changed", result["error"])
            self.assertEqual(result["downloads"], [])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(result["runner"]["resource_calls"], 0)

    def test_only_accepts_changed_run_and_observer_sources(self):
        with self.copied_entrypoints() as here:
            for name in ("run.py", "query_observer.py"):
                with self.subTest(source=name):
                    self.build()
                    source = here / name
                    source.write_text(source.read_text() + "\n# 観測処理の変更\n")
                    result = self.attempt(only="go")
                    current = json.loads((self.output / "buildinputs.json").read_text())
                    self.record(source=name, partial=result, recorded_sha256=current["driver_sources"][name])
                    self.assertTrue(result["accepted"], result)
                    self.assertEqual(current["driver_sources"][name], build.digest(source))
                    self.assertEqual(result["runner"]["resource_calls"], 1)

    def test_only_rejects_changed_snapshot_pins_before_acquisition(self):
        with self.copied_entrypoints() as here:
            self.build()
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            self.pins["java_currentSnapshot"]["jar_sha256"] = "f" * 64
            build.save(here / "snapshots.json", self.pins)
            result = self.attempt(only="go")
            self.record(partial=result, compiler_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == calls)
            self.assertFalse(result["accepted"], result)
            self.assertIn("current pins", result["error"])
            self.assertEqual(result["downloads"], [])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(result["runner"]["resource_calls"], 0)

    def test_acquire_recovers_forged_readable_cached_archive(self):
        url = self.source_url("java")
        original = self.archives[url]
        for mode in ("modified", "incomplete"):
            with self.subTest(mode=mode):
                self.output = self.root / mode
                (self.output / "sources").mkdir(parents=True)
                files = {"src/main/java/Fixture.java": b"class Fixture {}\n"}
                if mode == "modified":
                    files["marker.txt"] = b"forged source under the requested commit name"
                self.add_archive("java", self.pins["sources"]["java"], files)
                archive = self.output / "sources/java.tar.gz"
                archive.write_bytes(self.archives[url])
                forged = self.file_state(archive)
                self.archives[url] = original
                result = self.attempt()
                final = self.file_state(archive)
                marker = self.output / "sources/java/marker.txt"
                self.record(mode=mode, forged=forged, forged_files={k: v.decode() for k, v in files.items()},
                            expected=self.pins["source_archives"]["java"], result=result, final=final,
                            marker=marker.read_text() if marker.exists() else None)
                self.assertNotEqual(forged["sha256"], self.pins["source_archives"]["java"]["sha256"])
                self.assertTrue(result["accepted"], result)
                self.assertEqual(final["sha256"], self.pins["source_archives"]["java"]["sha256"])
                self.assertEqual(marker.read_text(), self.pins["sources"]["java"])
                self.assertEqual(len(result["downloads"]), 6)
                self.assertEqual(result["runner"]["resource_calls"], 1)

    def test_acquire_rejects_forged_readable_download_then_retries(self):
        url = self.source_url("java")
        original = self.archives[url]
        for mode in ("modified", "incomplete"):
            with self.subTest(mode=mode):
                self.output = self.root / mode
                self.output.mkdir()
                self.build()
                previous = (self.output / "source-inputs.json").read_bytes()
                calls = (self.output / "tool-calls.jsonl").read_bytes()
                archive = self.output / "sources/java.tar.gz"
                archive.unlink()
                files = {"src/main/java/Fixture.java": b"class Fixture {}\n"}
                if mode == "modified":
                    files["marker.txt"] = b"forged downloaded source"
                self.add_archive("java", self.pins["sources"]["java"], files)
                failure = self.attempt()
                failed_cache = self.file_state(archive)
                retained_record = (self.output / "source-inputs.json").read_bytes() == previous
                tools_unchanged = (self.output / "tool-calls.jsonl").read_bytes() == calls
                self.archives[url] = original
                retry = self.attempt()
                self.record(mode=mode, failure=failure, failed_cache=failed_cache,
                            previous_source_record_retained=retained_record, tools_unchanged=tools_unchanged,
                            retry=retry, final=self.file_state(archive))
                self.assertFalse(failure["accepted"], failure)
                self.assertIn("source archive digest mismatch", failure["error"])
                self.assertFalse(failed_cache["exists"])
                self.assertTrue(retained_record)
                self.assertTrue(tools_unchanged)
                self.assertEqual(failure["metadata"], {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
                self.assertEqual(failure["runner"]["resource_calls"], 0)
                self.assertTrue(retry["accepted"], retry)
                self.assertEqual(len(retry["downloads"]), 1)
                self.assertEqual(retry["runner"]["resource_calls"], 1)

    def test_acquire_rejects_source_pin_without_matching_archive_pin(self):
        self.pins["sources"]["go"] = "f" * 40
        self.add_archive("go", self.pins["sources"]["go"], {
            "marker.txt": self.pins["sources"]["go"].encode(),
            "go.mod": b"module github.com/j5ik2o/event-store-adapter-go/v2\n", "go.sum": b""})
        result = self.attempt()
        self.record(source_sha=self.pins["sources"]["go"], archive_pin=self.pins["source_archives"]["go"], result=result)
        self.assertFalse(result["accepted"], result)
        self.assertIn("source archive pin mismatch", result["error"])
        self.assertEqual(result["downloads"], [])
        self.assertEqual(result["runner"]["resource_calls"], 0)

    def test_java_recovers_invalid_cache_from_supplied_or_official_artifact(self):
        snapshot = self.pins["java_currentSnapshot"]
        for supplied in (True, False):
            for suffix, key in ((".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")):
                with self.subTest(supplied=supplied, suffix=suffix):
                    self.output = self.root / f"{supplied}{suffix}"
                    self.output.mkdir()
                    self.build()
                    path = self.output / (snapshot["artifact"] + suffix)
                    path.write_bytes(b"partial cached Java artifact")
                    before = self.file_state(path)
                    result = self.attempt(supplied=supplied)
                    after = self.file_state(path)
                    self.record(supplied=supplied, suffix=suffix, before=before, result=result, after=after, expected=snapshot[key])
                    self.assertTrue(result["accepted"], result)
                    self.assertEqual(after["sha256"], snapshot[key])
                    self.assertEqual(len(result["downloads"]), 0 if supplied else 1)
                    if not supplied:
                        self.assertEqual(result["downloads"][0]["url"], snapshot["repository"] + path.name)
                    self.assertEqual(result["runner"]["resource_calls"], 1)
                    self.assertFalse(result["metadata"]["build-failure.json"])

    def test_java_rejects_invalid_explicit_artifact_without_network_fallback(self):
        snapshot = self.pins["java_currentSnapshot"]
        for suffix in (".jar", "-sources.jar"):
            for cached in ("valid", "invalid", "missing"):
                with self.subTest(suffix=suffix, cached=cached):
                    self.output = self.root / (suffix + cached)
                    self.output.mkdir()
                    self.build()
                    path = self.output / (snapshot["artifact"] + suffix)
                    if cached == "invalid":
                        path.write_bytes(b"partial output cache")
                    elif cached == "missing":
                        path.unlink()
                    supplied = self.supplied / path.name
                    original = supplied.read_bytes()
                    supplied.write_bytes(b"invalid explicitly supplied artifact")
                    bad_supplied = self.file_state(supplied)
                    result = self.attempt()
                    supplied.write_bytes(original)
                    self.record(suffix=suffix, cached=cached, supplied=bad_supplied, result=result)
                    self.assertFalse(result["accepted"], result)
                    self.assertIn("Java currentSnapshot digest mismatch", result["error"])
                    self.assertEqual(result["downloads"], [])
                    self.assertEqual(result["runner"]["resource_calls"], 0)
                    self.assertFalse(result["metadata"]["drivers.json"])

    def test_java_interrupted_copy_or_download_retries_same_output(self):
        snapshot = self.pins["java_currentSnapshot"]
        for mode in ("copy", "download"):
            for suffix, key in ((".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")):
                with self.subTest(mode=mode, suffix=suffix):
                    self.output = self.root / (mode + suffix)
                    self.output.mkdir()
                    name = snapshot["artifact"] + suffix
                    original_copy, original_write = build.shutil.copyfile, Path.write_bytes
                    partial = []

                    def interrupt_write(path, data):
                        original_write(path, data[:12])
                        partial.append(dict(path=str(path), **self.file_state(path)))
                        raise RuntimeError("fixture Java transfer interrupted")

                    def copy(source, destination, **kwargs):
                        if Path(destination).name == name:
                            return interrupt_write(Path(destination), Path(source).read_bytes())
                        return original_copy(source, destination, **kwargs)

                    def write(path, data):
                        if path.name == name:
                            return interrupt_write(path, data)
                        return original_write(path, data)

                    with (mock.patch.object(build.shutil, "copyfile", side_effect=copy) if mode == "copy"
                          else mock.patch.object(Path, "write_bytes", new=write)):
                        failure = self.attempt(supplied=mode == "copy")
                    failed_cache = self.file_state(self.output / name)
                    retry = self.attempt(supplied=mode == "copy")
                    self.record(mode=mode, suffix=suffix, partial=partial, failed_cache=failed_cache, failure=failure,
                                retry=retry, final=self.file_state(self.output / name))
                    self.assertIn("fixture Java transfer interrupted", failure["error"])
                    self.assertEqual(len(partial), 1)
                    self.assertFalse(failed_cache["exists"])
                    self.assertEqual(failure["runner"]["resource_calls"], 0)
                    self.assertTrue(retry["accepted"], retry)
                    self.assertEqual(build.digest(self.output / name), snapshot[key])
                    self.assertEqual(retry["runner"]["resource_calls"], 1)

    def test_java_rejects_invalid_download_then_retries(self):
        snapshot = self.pins["java_currentSnapshot"]
        for suffix, key in ((".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")):
            with self.subTest(suffix=suffix):
                self.output = self.root / suffix
                self.output.mkdir()
                self.build()
                path = self.output / (snapshot["artifact"] + suffix)
                path.write_bytes(b"broken output artifact")
                url = snapshot["repository"] + path.name
                original = self.archives[url]
                self.archives[url] = b"invalid downloaded Java artifact"
                failure = self.attempt(supplied=False)
                failed_cache = self.file_state(path)
                self.archives[url] = original
                retry = self.attempt(supplied=False)
                self.record(suffix=suffix, failure=failure, failed_cache=failed_cache,
                            retry=retry, final=self.file_state(path), expected=snapshot[key])
                self.assertFalse(failure["accepted"], failure)
                self.assertIn("Java currentSnapshot digest mismatch", failure["error"])
                self.assertFalse(failed_cache["exists"])
                self.assertEqual(len(failure["downloads"]), 1)
                self.assertEqual(failure["runner"]["resource_calls"], 0)
                self.assertTrue(retry["accepted"], retry)
                self.assertEqual(len(retry["downloads"]), 1)
                self.assertEqual(build.digest(path), snapshot[key])
                self.assertEqual(retry["runner"]["resource_calls"], 1)

    def test_java_sources_must_match_pin_before_cache_commit(self):
        snapshot = self.pins["java_currentSnapshot"]
        path = self.supplied / (snapshot["artifact"] + "-sources.jar")
        with zipfile.ZipFile(path, "w") as package:
            package.writestr(zipfile.ZipInfo("Fixture.java"), b"class Other {}\n")
        snapshot["sources_sha256"] = build.digest(path)
        result = self.attempt()
        cached = self.file_state(self.output / path.name)
        self.record(supplied=self.file_state(path), cached=cached, result=result)
        self.assertFalse(result["accepted"], result)
        self.assertIn("Java published sources do not match the pinned source", result["error"])
        self.assertFalse(cached["exists"])
        self.assertEqual(result["runner"]["resource_calls"], 0)

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
