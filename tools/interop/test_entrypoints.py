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
import tomllib
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
        (self.root / "lib").mkdir()
        (self.root / "lib/gradle-launcher-fixture.jar").write_bytes(b"fixture installation")
        # 外部ビルドだけを代替し、生成物の列挙・取得・成功記録は実入口に任せる。
        executable = "#!" + sys.executable + "\n" + '''
import json, os, sys
from pathlib import Path
output = Path(os.environ["INTEROP_TEST_OUTPUT"])
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
with (output / "tool-calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"tool": tool, "args": args, "gowork": os.environ.get("GOWORK"),
        "cargo_home": os.environ.get("CARGO_HOME"),
        "goflags": os.environ.get("GOFLAGS"), "goenv": os.environ.get("GOENV"),
        "cargo_environment": {name: os.environ.get(name) for name in
            ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR", "CARGO_BUILD_BUILD_DIR")}}) + "\\n")
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
    if (output / "fail-cargo-build").exists():
        raise SystemExit(27)
    write(output / "rust-driver/Cargo.lock", b"rust lock fixture")
    target = Path(os.environ.get("CARGO_TARGET_DIR") or os.environ.get("CARGO_BUILD_TARGET_DIR") or output / "rust-driver/target")
    write(target / "debug/interop-driver", b"rust fixture")
    write(Path(os.environ["CARGO_HOME"]) / "registry/src/fixture/normal/Cargo.toml", b"normal registry fixture")
elif tool == "cargo" and args[0] == "metadata":
    if os.environ.get("CARGO_LOG"):
        print("TRACE cargo::core::resolver: fixture diagnostic", file=sys.stderr)
    if (output / "fail-cargo-metadata").exists():
        print("partial metadata")
        raise SystemExit(29)
    registry = Path(os.environ["CARGO_HOME"]) / "registry/src/fixture/normal/Cargo.toml"
    if (output / "foreign-cargo-metadata").exists():
        registry = Path((output / "foreign-cargo-metadata").read_text())
    print(json.dumps({"target_directory": str(Path(os.environ.get("CARGO_TARGET_DIR") or
        os.environ.get("CARGO_BUILD_TARGET_DIR") or output / "rust-driver/target")), "packages": [
            {"name": "interop-driver", "source": None, "manifest_path": str(output / "rust-driver/Cargo.toml")},
            {"name": "event-store-adapter-rs", "source": None, "manifest_path": str(output / "sources/rs/lib/Cargo.toml")},
            {"name": "normal", "source": "registry+fixture", "manifest_path": str(registry)}]}))
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

    def test_cargo_each_selected_build_uses_new_home_and_preserves_previous_and_parent(self):
        inherited = self.root / "inherited-cargo-home"
        for name in ("registry/src/fixture/normal/Cargo.toml", "registry/cache/fixture/normal.crate", "credentials.toml"):
            path = inherited / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"retained ordinary parent fixture")
        before = build.source_inventory(inherited, "go")
        homes = []
        with mock.patch.dict(os.environ, {"CARGO_HOME": str(inherited)}):
            for only in (None, "rust", None):
                prior = {str(home): build.source_inventory(home, "go") for home in homes}
                self.build(only=only)
                inputs = json.loads((self.output / "buildinputs.json").read_text())
                home = Path(inputs["cargo_build_environment"]["CARGO_HOME"])
                self.assertEqual(home.parent, self.output.resolve())
                self.assertTrue(home.is_dir())
                self.assertFalse(home.is_symlink())
                self.assertNotIn(home, homes)
                self.assertNotEqual(home, inherited)
                self.assertEqual(inputs["cargo_config_inputs"]["cargo_home"], str(home))
                self.assertEqual(inputs["cargo_metadata_inputs"]["cargo_home"], str(home))
                self.assertEqual(inputs["cargo_metadata_inputs"]["registry_packages"], 1)
                self.assertFalse((home / "credentials.toml").exists())
                self.assertFalse((home / "registry/cache/fixture/normal.crate").exists())
                self.assertEqual((home / "registry/src/fixture/normal/Cargo.toml").read_bytes(), b"normal registry fixture")
                self.assertEqual({str(old): build.source_inventory(old, "go") for old in homes}, prior)
                homes.append(home)
                self.assertEqual(os.environ["CARGO_HOME"], str(inherited))
            calls = [json.loads(line) for line in (self.output / "tool-calls.jsonl").read_text().splitlines()]
            cargo = [row for row in calls if row["tool"] == "cargo"]
            self.assertEqual([row["cargo_home"] for row in cargo], [str(home) for home in homes for _ in range(2)])
            self.assertTrue(all(row["cargo_home"] == str(inherited) for row in calls if row["tool"] != "cargo"))
        self.assertEqual(build.source_inventory(inherited, "go"), before)
        unselected = build.source_inventory(homes[-1], "go")
        self.build(only="go")
        inputs = json.loads((self.output / "buildinputs.json").read_text())
        self.assertEqual(inputs["cargo_build_environment"]["CARGO_HOME"], str(homes[-1]))
        self.assertEqual(build.source_inventory(homes[-1], "go"), unselected)
        self.assertEqual(len(list(self.output.glob(".cargo-home-*"))), 3)
        self.assertEqual(self.probe_run()["resource_calls"], 1)
        self.record(homes=[str(home) for home in homes], cargo_calls=cargo, parent_preserved=True)

    def test_cargo_home_link_added_during_acquisition_preserves_external_files(self):
        self.build()
        external = self.root / "other-owner-home"
        external.mkdir()
        (external / "keep").write_bytes(b"other owner")
        before = build.source_inventory(external, "go")
        acquire = build.acquire
        homes = set(self.output.resolve().glob(".cargo-home-*"))

        def acquire_then_link(output):
            sources = acquire(output)
            home = (set(output.glob(".cargo-home-*")) - homes).pop()
            home.rename(output / "retained-new-home")
            home.symlink_to(external, target_is_directory=True)
            return sources

        with mock.patch.object(build, "acquire", side_effect=acquire_then_link), \
                mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as child:
            attempt = self.attempt(only="rust")
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("Cargo home must be a real directory", attempt["error"])
        self.assertFalse(any(Path(call.args[0][0]).name == "cargo" for call in child.call_args_list))
        self.assertEqual(build.source_inventory(external, "go"), before)
        self.assertEqual(attempt["runner"]["resource_calls"], 0)
        self.record(attempt=attempt, external_preserved=True)

    def test_cargo_metadata_rejects_registry_source_outside_new_home(self):
        self.build()
        external = self.root / "shared-registry/Cargo.toml"
        external.parent.mkdir()
        external.write_bytes(b"ordinary shared source")
        (self.output / "foreign-cargo-metadata").write_text(str(external))
        attempt = self.attempt(only="rust")
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("Cargo registry source must be inside the fresh Cargo home", attempt["error"])
        self.assertEqual(external.read_bytes(), b"ordinary shared source")
        self.assertEqual(attempt["runner"]["resource_calls"], 0)
        self.record(attempt=attempt, external_preserved=True)

    def test_cargo_build_failure_retains_new_home_and_invalidates_success(self):
        self.build()
        previous = set(self.output.glob(".cargo-home-*"))
        (self.output / "fail-cargo-build").touch()
        attempt = self.attempt(only="rust")
        row = json.loads((self.output / "build-failure.json").read_text())["commands"][-1]
        self.assertFalse(attempt["accepted"], attempt)
        self.assertEqual(row["label"], "rust")
        self.assertEqual(row["exit"], 27)
        self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
        self.assertEqual(len(set(self.output.glob(".cargo-home-*")) - previous), 1)
        self.assertTrue(all(home.is_dir() for home in previous))
        self.assertEqual(attempt["runner"]["resource_calls"], 0)
        self.record(attempt=attempt, command=row)

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

    def test_jvm_output_symlinks_preserve_both_children_before_acquisition(self):
        for name in ("jvm", "jvm/classes", "jvm/resources"):
            with self.subTest(input=name):
                self.build()
                path = self.output / name
                path.mkdir(parents=True, exist_ok=True)
                saved = self.root / ("saved-" + name.replace("/", "-"))
                path.rename(saved)
                foreign = self.root / ("owner-" + name.replace("/", "-"))
                for child in ("classes", "resources"):
                    (foreign / child).mkdir(parents=True)
                    (foreign / child / "keep").write_text("別所有者の入力")
                path.symlink_to(foreign, target_is_directory=True)
                before = build.source_inventory(foreign, "go")
                calls = (self.output / "tool-calls.jsonl").read_bytes()
                try:
                    with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                        attempt = self.attempt()
                    after = build.source_inventory(foreign, "go")
                    self.record(input=name, attempt=attempt, foreign_before=before, foreign_after=after,
                                acquisition_calls=acquire.call_count)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("JVM output directory", attempt["error"])
                    self.assertEqual(before, after)
                    self.assertTrue(path.is_symlink())
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                finally:
                    path.unlink()
                    saved.rename(path)

    def test_jvm_full_and_partial_regenerate_only_owned_children(self):
        gradle = self.bin / "gradle"
        gradle.write_text(gradle.read_text() + '\nif tool == "gradle": write(jvm / "resources/main/generated", b"resource")\n')
        self.build()
        kept = [self.output / "jvm/user-resource", self.output / "gradle-cache/keep"]
        for path in kept:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("保持する入力")
        for only in (None, "jvm"):
            with self.subTest(only=only):
                inputs = json.loads((self.output / "buildinputs.json").read_text())
                other = [row for row in inputs["artifacts"] if "jvm" not in Path(row["path"]).parts]
                with mock.patch.object(build.shutil, "rmtree", wraps=shutil.rmtree) as cleanup:
                    self.build(only=only)
                removed = [call.args[0] for call in cleanup.call_args_list]
                self.assertIn(self.output.resolve() / "jvm/classes", removed)
                self.assertIn(self.output.resolve() / "jvm/resources", removed)
                self.assertTrue((self.output / "jvm/classes/main/Fixture.class").exists())
                self.assertEqual((self.output / "jvm/resources/main/generated").read_bytes(), b"resource")
                self.assertTrue(all(path.read_text() == "保持する入力" for path in kept))
                if only:
                    self.assertTrue(all(build.digest(Path(row["path"])) == row["sha256"] for row in other))
                self.record(only=only, cleaned=[str(path) for path in removed], runner=self.probe_run())

    def test_go_build_and_list_disable_parent_and_explicit_workspaces(self):
        workfile = self.root / "go.work"
        workfile.write_text("go 1.26.0\nuse ./build/go-driver\n")
        before = workfile.read_bytes()
        for gowork in ("", str(workfile)):
            with self.subTest(gowork=gowork), mock.patch.dict(os.environ, {"GOWORK": gowork}):
                self.build()
                self.build(only="go")
                calls = [json.loads(line) for line in (self.output / "tool-calls.jsonl").read_text().splitlines()]
                go_calls = [row for row in calls if row["tool"] == "go"]
                self.record(go_calls=go_calls, parent_gowork=os.environ["GOWORK"])
                self.assertTrue(go_calls)
                self.assertTrue(all(row["gowork"] == "off" for row in go_calls))
                self.assertEqual(os.environ["GOWORK"], gowork)
                self.assertEqual(workfile.read_bytes(), before)

    def test_generated_paths_preserve_spaces_quotes_backslashes_and_unicode(self):
        for name in ('output with spaces', '日本語 "引用"', 'rust \\path'):
            with self.subTest(path=name):
                self.output = self.root / name
                self.output.mkdir()
                self.build()
                cargo = tomllib.loads((self.output / "rust-driver/Cargo.toml").read_text())
                self.assertEqual(cargo["dependencies"]["event-store-adapter-rs"]["path"], str(self.output.resolve() / "sources/rs/lib"))
                # Go自身が非Windows上のバックスラッシュ付き置換先を拒否するため、ここはRustの字句だけを確認する。
                if "\\" in name:
                    self.record(path=str(self.output), rust_dependency_path=cargo["dependencies"]["event-store-adapter-rs"]["path"])
                    continue
                result = subprocess.run(["go", "mod", "edit", "-json"], cwd=self.output / "go-driver",
                                        env=build.child_environment({"GOWORK": "off"}), capture_output=True, text=True)
                self.record(path=str(self.output), exit=result.returncode, stdout=result.stdout, stderr=result.stderr)
                self.assertEqual(result.returncode, 0, result.stderr)
                replacement = json.loads(result.stdout)["Replace"][0]["New"]["Path"]
                self.assertEqual(replacement, str(self.output.resolve() / "sources/go"))

    def test_cargo_rejects_applicable_config_without_reading_or_modifying_it(self):
        with self.copied_entrypoints() as here:
            home = self.root / "cargo-home"
            home.mkdir()
            configs = [here / ".cargo/config.toml", here.parent / ".cargo/config", home / "config.toml", home / "config"]
            with mock.patch.dict(os.environ, {"CARGO_HOME": str(home)}):
                for config in configs:
                    with self.subTest(config=str(config)):
                        self.build()
                        config.parent.mkdir(exist_ok=True)
                        contents = b'[build]\nrustc-wrapper = "unrecorded-wrapper"\n'
                        config.write_bytes(contents)
                        calls = (self.output / "tool-calls.jsonl").read_bytes()
                        try:
                            with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                                attempt = self.attempt(only="rust")
                            self.record(config=str(config), attempt=attempt, acquisition_calls=acquire.call_count)
                            self.assertFalse(attempt["accepted"], attempt)
                            self.assertIn("unrecorded Cargo configuration", attempt["error"])
                            self.assertEqual(acquire.call_count, 0)
                            self.assertEqual(config.read_bytes(), contents)
                            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                        finally:
                            config.unlink()

    def test_cargo_rejects_compiler_and_wrapper_environment_without_disclosing_values(self):
        self.build()
        for name in ("RUSTC", "CARGO_BUILD_RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                     "CARGO_BUILD_RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER"):
            with self.subTest(variable=name), mock.patch.dict(os.environ, {name: "private-marker-value"}):
                with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                    attempt = self.attempt()
                self.record(variable=name, attempt=attempt, acquisition_calls=acquire.call_count)
                self.assertFalse(attempt["accepted"], attempt)
                self.assertIn(name, attempt["error"])
                self.assertNotIn("private-marker-value", attempt["error"])
                self.assertEqual(acquire.call_count, 0)
                self.assertEqual(os.environ[name], "private-marker-value")

    def test_sources_parent_link_preserves_foreign_inventory_before_acquisition(self):
        foreign = self.root / "foreign-source-cache"
        foreign.mkdir()
        (foreign / "go.tar.gz").write_bytes(b"other owner incomplete archive")
        destination = foreign / f"event-store-adapter-go-{self.pins['sources']['go']}"
        destination.mkdir()
        (destination / "marker.txt").write_text(self.pins["sources"]["go"])
        before = build.source_inventory(foreign, "go")
        (self.output / "sources").symlink_to(foreign, target_is_directory=True)
        with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
            attempt = self.attempt()
        after = build.source_inventory(foreign, "go")
        self.record(attempt=attempt, acquisition_calls=acquire.call_count, foreign_before=before, foreign_after=after)
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("source cache directory", attempt["error"])
        self.assertEqual(acquire.call_count, 0)
        self.assertEqual(attempt["downloads"], [])
        self.assertFalse((self.output / "tool-calls.jsonl").exists())
        self.assertEqual(attempt["runner"]["resource_calls"], 0)
        self.assertEqual(attempt["runner"]["driver_calls"], 0)
        self.assertEqual(before, after)
        self.assertTrue((self.output / "sources").is_symlink())
        with mock.patch.object(build, "PINS", self.pins), mock.patch.object(build.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(RuntimeError, "source cache directory"):
                build.acquire(self.output)
            self.assertEqual(download.call_count, 0)
        self.assertEqual(build.source_inventory(foreign, "go"), before)

    def test_sources_parent_rejects_files_and_dangling_links_without_mutation(self):
        root = self.output / "sources"
        for mode in ("file", "dangling-link"):
            with self.subTest(mode=mode):
                if mode == "file":
                    root.write_bytes(b"foreign file")
                else:
                    root.symlink_to(self.root / "missing-foreign-directory", target_is_directory=True)
                try:
                    with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                        attempt = self.attempt()
                    self.record(mode=mode, attempt=attempt, acquisition_calls=acquire.call_count)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("source cache directory", attempt["error"])
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual(attempt["downloads"], [])
                    self.assertFalse((self.output / "tool-calls.jsonl").exists())
                    if mode == "file":
                        self.assertEqual(root.read_bytes(), b"foreign file")
                    else:
                        self.assertTrue(root.is_symlink())
                finally:
                    root.unlink()

    def test_go_children_control_flags_and_persisted_environment_without_parent_changes(self):
        config = self.root / "go-environment"
        config.write_text("GOFLAGS=-overlay=private-overlay.json\n")
        environment = {"GOFLAGS": "-overlay=private-overlay.json", "GOENV": str(config), "GOWORK": "private-go.work"}
        with mock.patch.dict(os.environ, environment):
            self.build()
            self.build(only="go")
            calls = [json.loads(line) for line in (self.output / "tool-calls.jsonl").read_text().splitlines()]
            go_calls = [row for row in calls if row["tool"] == "go"]
            self.record(go_calls=go_calls, parent_environment=environment)
            self.assertEqual([row["args"][0] for row in go_calls], ["mod", "build", "list", "mod", "build", "list"])
            self.assertTrue(all(row["goflags"] == "" and row["goenv"] == "off" and row["gowork"] == "off" for row in go_calls))
            self.assertTrue(all(os.environ[name] == value for name, value in environment.items()))
        self.assertEqual(config.read_text(), "GOFLAGS=-overlay=private-overlay.json\n")

    def test_cargo_build_and_metadata_use_recorded_target_and_preserve_external_output(self):
        external = self.root / "external-target"
        external.mkdir()
        (external / "keep").write_bytes(b"other owner target")
        before = build.source_inventory(external, "go")
        environment = {name: str(external) for name in ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR", "CARGO_BUILD_BUILD_DIR")}
        with mock.patch.dict(os.environ, environment):
            self.build()
            self.build(only="rust")
            calls = [json.loads(line) for line in (self.output / "tool-calls.jsonl").read_text().splitlines()]
            cargo_calls = [row for row in calls if row["tool"] == "cargo"]
            target = str(self.output.resolve() / "rust-driver/target")
            self.record(cargo_calls=cargo_calls, external_before=before, external_after=build.source_inventory(external, "go"))
            self.assertEqual([row["args"][0] for row in cargo_calls], ["build", "metadata", "build", "metadata"])
            self.assertTrue(all(all(value == target for value in row["cargo_environment"].values()) for row in cargo_calls))
            inputs = json.loads((self.output / "buildinputs.json").read_text())
            self.assertEqual(inputs["drivers"]["rs"]["argv"], [str(Path(target) / "debug/interop-driver")])
            self.assertTrue(all(os.environ[name] == value for name, value in environment.items()))
        self.assertEqual(build.source_inventory(external, "go"), before)

    def test_cargo_rejects_target_and_output_flags_before_acquisition_without_disclosure(self):
        for name in ("CARGO_BUILD_TARGET", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS", "CARGO_TARGET_AARCH64_APPLE_DARWIN_RUSTFLAGS"):
            with self.subTest(variable=name), mock.patch.dict(os.environ, {name: "private-output-override"}):
                with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                    attempt = self.attempt()
                self.record(variable=name, attempt=attempt, acquisition_calls=acquire.call_count)
                self.assertFalse(attempt["accepted"], attempt)
                self.assertIn(name, attempt["error"])
                self.assertNotIn("private-output-override", attempt["error"])
                self.assertEqual(acquire.call_count, 0)
                self.assertEqual(os.environ[name], "private-output-override")

    def test_cargo_rejects_target_linkers_before_children_on_full_and_partial_builds(self):
        for name in ("CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER", "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"):
            for only in (None, "rust"):
                with self.subTest(variable=name, only=only):
                    self.build()
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    with mock.patch.dict(os.environ, {name: "private-linker-path"}), \
                            mock.patch.object(build, "acquire", wraps=build.acquire) as acquire, \
                            mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as child:
                        attempt = self.attempt(only=only)
                        self.assertEqual(os.environ[name], "private-linker-path")
                    self.record(variable=name, only=only, attempt=attempt,
                                acquisition_calls=acquire.call_count, subprocess_calls=child.call_count)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn(name, attempt["error"])
                    self.assertNotIn("private-linker-path", attempt["error"])
                    self.assertNotIn("private-linker-path", (self.output / "build-failure.json").read_text())
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual(child.call_count, 0)
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_cargo_metadata_parses_stdout_and_retains_stderr_on_full_and_partial_builds(self):
        with mock.patch.dict(os.environ, {"CARGO_LOG": "cargo::core::resolver=trace"}):
            self.build()
            self.build(only="rust")
            self.assertEqual(os.environ["CARGO_LOG"], "cargo::core::resolver=trace")
        rows = [row for row in json.loads((self.output / "build-commands.json").read_text()) if row["label"] == "rust-inputs"]
        self.record(commands=rows, metadata=self.metadata())
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["exit"], 0)
            self.assertIn("fixture diagnostic", Path(row["log"]).read_text())
            metadata = json.loads(Path(row["stdout"]).read_text())
            self.assertEqual(Path(metadata["target_directory"]), self.output.resolve() / "rust-driver/target")
        self.assertFalse(self.metadata()["build-failure.json"])
        self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_cargo_metadata_failure_retains_actual_exit_and_invalidates_success(self):
        self.build()
        (self.output / "fail-cargo-metadata").touch()
        with mock.patch.dict(os.environ, {"CARGO_LOG": "cargo::core::resolver=trace"}):
            attempt = self.attempt(only="rust")
        row = json.loads((self.output / "build-failure.json").read_text())["commands"][-1]
        self.record(attempt=attempt, command=row)
        self.assertFalse(attempt["accepted"], attempt)
        self.assertEqual(row["label"], "rust-inputs")
        self.assertEqual(row["exit"], 29)
        self.assertEqual(Path(row["stdout"]).read_text(), "partial metadata\n")
        self.assertIn("fixture diagnostic", Path(row["log"]).read_text())
        self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False, "build-failure.json": True})
        self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_jvm_directory_links_rejected_before_acquisition_and_compilation(self):
        for name in ("drivers", "drivers/jvm", "drivers/jvm/linked", "drivers/jvm/.hidden/linked"):
            for only in (None, "jvm"):
                with self.subTest(path=name, only=only), self.copied_entrypoints() as here:
                    self.build()
                    path = here / name
                    foreign = self.root / "other-owner-jvm"
                    foreign.mkdir(exist_ok=True)
                    (foreign / "Linked.kt").write_text("class LinkedKotlin\n")
                    (foreign / "Linked.scala").write_text("class LinkedScala\n")
                    previous = build.source_inventory(foreign, "go")
                    saved = self.root / "saved-jvm-source"
                    if path.exists():
                        path.rename(saved)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(foreign, target_is_directory=True)
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    try:
                        with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                            attempt = self.attempt(only=only)
                        self.record(path=name, only=only, attempt=attempt, acquisition_calls=acquire.call_count)
                        self.assertFalse(attempt["accepted"], attempt)
                        self.assertIn("JVM source directory", attempt["error"])
                        self.assertEqual(acquire.call_count, 0)
                        self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                        self.assertEqual(build.source_inventory(foreign, "go"), previous)
                        self.assertTrue(path.is_symlink())
                        self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    finally:
                        path.unlink()
                        if saved.exists():
                            saved.rename(path)
                        shutil.rmtree(here)

    def test_jvm_directory_links_block_measurement_and_unselected_partial_build(self):
        with self.copied_entrypoints() as here:
            self.build()
            foreign = self.root / "linked-jvm-source"
            foreign.mkdir()
            (foreign / "Linked.kt").write_text("class LinkedKotlin\n")
            path = here / "drivers/jvm/.linked"
            path.symlink_to(foreign, target_is_directory=True)
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            runner = self.probe_run()
            attempt = self.attempt(only="go")
            self.record(runner=runner, partial=attempt)
            self.assertEqual(runner["resource_calls"], 0)
            self.assertFalse(attempt["accepted"], attempt)
            self.assertIn("JVM source directory", attempt["error"])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(attempt["downloads"], [])

    def test_dangling_jvm_links_rejected_before_acquisition_and_compilation(self):
        with self.copied_entrypoints() as here:
            self.build()
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            target = self.root / "other-owner-missing-source"
            for name in ("linked", ".hidden/linked", "Missing.kt", "Missing.scala"):
                for only in (None, "jvm", "go"):
                    with self.subTest(path=name, only=only):
                        path = here / "drivers/jvm" / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.symlink_to(target)
                        try:
                            listing = next(os.walk(path.parent, followlinks=False))
                            self.assertIn(path.name, listing[2])
                            with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                                attempt = self.attempt(only=only)
                            self.record(path=name, only=only, attempt=attempt, acquisition_calls=acquire.call_count)
                            self.assertFalse(attempt["accepted"], attempt)
                            self.assertIn("JVM source", attempt["error"])
                            self.assertEqual(acquire.call_count, 0)
                            self.assertEqual(attempt["downloads"], [])
                            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                            self.assertEqual(attempt["runner"]["resource_calls"], 0)
                            self.assertTrue(path.is_symlink())
                            self.assertFalse(target.exists())
                        finally:
                            path.unlink()

    def test_dangling_jvm_link_added_during_acquisition_rejected_before_compile_cleanup(self):
        with self.copied_entrypoints() as here:
            self.build()
            classes = build.source_inventory(self.output / "jvm/classes", "go")
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            target = self.root / "other-owner-late-missing-source"
            path = here / "drivers/jvm/.hidden/late-link"
            acquire = build.acquire

            def acquire_then_add_link(output):
                sources = acquire(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(target)
                return sources

            with mock.patch.object(build, "acquire", side_effect=acquire_then_add_link) as acquisition:
                attempt = self.attempt()
            self.record(attempt=attempt, acquisition_calls=acquisition.call_count)
            self.assertFalse(attempt["accepted"], attempt)
            self.assertIn("JVM source", attempt["error"])
            self.assertEqual(acquisition.call_count, 1)
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
            self.assertTrue(path.is_symlink())
            self.assertFalse(target.exists())
            self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_dangling_jvm_link_blocks_measurement_before_resources(self):
        with self.copied_entrypoints() as here:
            self.build()
            target = self.root / "other-owner-missing-source"
            for name in ("linked", ".hidden/linked", "Missing.kt", "Missing.scala"):
                with self.subTest(path=name):
                    path = here / "drivers/jvm" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(target)
                    try:
                        runner = self.probe_run()
                        self.record(path=name, runner=runner)
                        self.assertEqual(runner["resource_calls"], 0)
                        self.assertEqual(runner["driver_calls"], 0)
                        self.assertIn("JVM source", runner["error"])
                        self.assertFalse(target.exists())
                        self.assertTrue(path.is_symlink())
                    finally:
                        path.unlink()

    def test_gradle_cache_link_rejected_before_acquisition_and_children(self):
        for only in (None, "jvm"):
            with self.subTest(only=only):
                self.build()
                cache = self.output / "gradle-cache"
                foreign = self.root / "other-owner-gradle-cache"
                foreign.mkdir(exist_ok=True)
                (foreign / "keep").write_bytes(b"other owner cache")
                cache.symlink_to(foreign, target_is_directory=True)
                before = build.source_inventory(foreign, "go")
                calls = (self.output / "tool-calls.jsonl").read_bytes()
                try:
                    with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire, \
                            mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as child:
                        attempt = self.attempt(only=only)
                    self.record(only=only, attempt=attempt, acquisition_calls=acquire.call_count,
                                subprocess_calls=child.call_count, foreign_inventory=before)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("gradle-cache", attempt["error"])
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual(child.call_count, 0 if only is None else 1)
                    if only:
                        self.assertEqual(child.call_args.args[0][0], "node")
                        self.assertIn("--verify", child.call_args.args[0])
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(build.source_inventory(foreign, "go"), before)
                    self.assertTrue(cache.is_symlink())
                    self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                          "build-failure.json": True})
                finally:
                    cache.unlink()

    def test_gradle_cache_added_during_acquisition_rejected_before_cleanup(self):
        self.build()
        classes = build.source_inventory(self.output / "jvm/classes", "go")
        foreign = self.root / "late-other-owner-gradle-cache"
        foreign.mkdir()
        (foreign / "keep").write_bytes(b"other owner cache")
        before = build.source_inventory(foreign, "go")
        acquire = build.acquire

        def acquire_then_link(output):
            sources = acquire(output)
            (output / "gradle-cache").symlink_to(foreign, target_is_directory=True)
            return sources

        with mock.patch.object(build, "acquire", side_effect=acquire_then_link), \
                mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as child:
            attempt = self.attempt()
        self.record(attempt=attempt, subprocess_calls=child.call_count)
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("gradle-cache", attempt["error"])
        self.assertEqual(child.call_count, 0)
        self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
        self.assertEqual(build.source_inventory(foreign, "go"), before)
        self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_gradle_regular_cache_reused_and_unselected_link_preserved(self):
        self.build()
        cache = self.output / "gradle-cache"
        cache.mkdir()
        (cache / "keep").write_bytes(b"existing project cache")
        before = build.source_inventory(cache, "go")
        self.build(only="jvm")
        self.assertEqual(build.source_inventory(cache, "go"), before)
        foreign = self.root / "unselected-project-cache"
        cache.rename(foreign)
        cache.symlink_to(foreign, target_is_directory=True)
        self.build(only="go")
        self.record(foreign_inventory=build.source_inventory(foreign, "go"), cache_link=cache.is_symlink())
        self.assertTrue(cache.is_symlink())
        self.assertEqual(build.source_inventory(foreign, "go"), before)
        self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_existing_jvm_file_links_keep_compile_source_fingerprints(self):
        with self.copied_entrypoints() as here:
            target = self.root / "other-owner-source-file"
            target.write_bytes(b"unchanged compile source\n")
            names = ("Linked.java", ".hidden/Linked.kt", ".hidden/Linked.scala")
            for name in names:
                path = here / "drivers/jvm" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(target)
            self.build()
            inputs = json.loads((self.output / "buildinputs.json").read_text())["driver_sources"]
            self.record(recorded=inputs, file_links=names)
            for name in names:
                self.assertEqual(inputs["drivers/jvm/" + name], build.digest(target))
                self.assertTrue((here / "drivers/jvm" / name).is_symlink())
            self.assertEqual(target.read_bytes(), b"unchanged compile source\n")
            self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_selected_rust_target_cache_is_retained_outside_fresh_target(self):
        for only in (None, "rust"):
            with self.subTest(only=only):
                self.build()
                target = self.output / "rust-driver/target"
                marker = target / "debug/.fingerprint/poisoned-dependency"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_bytes(b"unrecorded dependency artifact and freshness")
                foreign = self.root / "other-owner-cache"
                foreign.mkdir(exist_ok=True)
                (foreign / "keep").write_bytes(b"other owner cache")
                (target / "other-owner-link").symlink_to(foreign, target_is_directory=True)
                previous = build.source_inventory(target, "go")
                lock = (self.output / "rust-driver/Cargo.lock").read_bytes()
                backups = set(self.output.glob(".rust-target-backup-*"))
                self.build(only=only)
                created = set(self.output.glob(".rust-target-backup-*")) - backups
                self.record(only=only, backups=[str(p) for p in created], old_inventory=previous,
                            marker_remains_in_selected_target=marker.exists())
                self.assertEqual(len(created), 1)
                backup = created.pop() / "target"
                self.assertEqual(build.source_inventory(backup, "go"), previous)
                self.assertFalse(marker.exists())
                self.assertFalse((target / "other-owner-link").exists())
                self.assertEqual((foreign / "keep").read_bytes(), b"other owner cache")
                self.assertEqual((self.output / "rust-driver/Cargo.lock").read_bytes(), lock)
                self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_unselected_rust_target_and_lock_are_unchanged(self):
        self.build()
        target = self.output / "rust-driver/target"
        (target / "keep").write_bytes(b"unselected Rust cache")
        previous = build.source_inventory(target, "go")
        lock = (self.output / "rust-driver/Cargo.lock").read_bytes()
        backups = set(self.output.glob(".rust-target-backup-*"))
        self.build(only="jvm")
        self.record(previous=previous, current=build.source_inventory(target, "go"))
        self.assertEqual(build.source_inventory(target, "go"), previous)
        self.assertEqual((self.output / "rust-driver/Cargo.lock").read_bytes(), lock)
        self.assertEqual(set(self.output.glob(".rust-target-backup-*")), backups)

    def test_hidden_jvm_fingerprints_cover_compile_inputs_without_unrelated_caches(self):
        with self.copied_entrypoints() as here:
            compiled = (".Injected.java", ".Injected.kt", ".Injected.scala", ".parent/Directory.kt",
                        ".parent/Directory.scala", "visible/.Nested.kt", "visible/.Nested.scala")
            unrelated = (".cache/data.bin", ".settings/config.json", ".parent/Directory.java")
            for name in compiled + unrelated:
                path = here / "drivers/jvm" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture input\n")
            self.build()
            inputs = json.loads((self.output / "buildinputs.json").read_text())["driver_sources"]
            self.record(recorded=inputs, compiled=compiled, unrelated=unrelated)
            for name in compiled:
                self.assertEqual(inputs["drivers/jvm/" + name], build.digest(here / "drivers/jvm" / name))
            for name in unrelated:
                self.assertNotIn("drivers/jvm/" + name, inputs)

    def test_hidden_jvm_changes_block_runner_and_unselected_partial_rebuild(self):
        with self.copied_entrypoints() as here:
            for name in (".Injected.java", ".Injected.kt", ".Injected.scala", ".parent/Directory.kt", ".parent/Directory.scala"):
                with self.subTest(source=name):
                    path = here / "drivers/jvm" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("original source\n")
                    self.build()
                    path.write_text("changed source\n")
                    runner = self.probe_run()
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    attempt = self.attempt(only="go")
                    self.record(source=name, runner=runner, partial=attempt)
                    self.assertEqual(runner["resource_calls"], 0)
                    self.assertIn("stale", runner["error"])
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("unselected driver sources changed", attempt["error"])
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(attempt["downloads"], [])

    def test_gradle_rejects_user_and_installation_init_scripts_without_reading_or_mutating(self):
        home = self.root / "gradle-home"
        scripts = [home / "init.gradle", home / "init.gradle.kts", home / "init.d/marker.gradle",
                   home / "init.d/marker.init.gradle.kts", self.root / "init.d/marker.init.gradle",
                   self.root / "init.d/marker.gradle.kts"]
        with mock.patch.dict(os.environ, {"GRADLE_USER_HOME": str(home)}):
            for script in scripts:
                with self.subTest(script=str(script)):
                    self.build()
                    script.parent.mkdir(parents=True, exist_ok=True)
                    content = b"private-init-script-content"
                    script.write_bytes(content)
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    classes = build.source_inventory(self.output / "jvm/classes", "go")
                    try:
                        with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                            attempt = self.attempt()
                        self.record(script=str(script), attempt=attempt, acquisition_calls=acquire.call_count)
                        self.assertFalse(attempt["accepted"], attempt)
                        self.assertIn("unrecorded Gradle initialization script", attempt["error"])
                        self.assertNotIn(content.decode(), attempt["error"])
                        self.assertEqual(acquire.call_count, 0)
                        self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                        self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                        self.assertEqual(script.read_bytes(), content)
                        self.assertEqual(os.environ["GRADLE_USER_HOME"], str(home))
                    finally:
                        script.unlink()

    def test_gradle_rechecks_init_scripts_before_jvm_cleanup_and_execution(self):
        home = self.root / "gradle-home"
        with mock.patch.dict(os.environ, {"GRADLE_USER_HOME": str(home)}):
            self.build()
            before = build.source_inventory(self.output / "jvm/classes", "go")
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            script = home / "init.gradle"
            acquire = build.acquire
            def acquire_then_add_script(output):
                sources = acquire(output)
                home.mkdir(exist_ok=True)
                script.write_text("harmless late init")
                return sources
            with mock.patch.object(build, "acquire", side_effect=acquire_then_add_script):
                attempt = self.attempt()
            self.record(attempt=attempt)
            self.assertFalse(attempt["accepted"], attempt)
            self.assertIn("unrecorded Gradle initialization script", attempt["error"])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), before)

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

    def test_js_generated_roots_require_real_directories_before_build(self):
        names = ("node_modules", "packages/library/node_modules", "packages/examples/node_modules",
                 "packages/tests/node_modules", "packages/library/dist")
        for name in names:
            for mode in ("directory-link", "dangling-link", "file", "fifo"):
                with self.subTest(path=name, mode=mode):
                    self.output = self.root / (name.replace("/", "-") + "-" + mode)
                    self.output.mkdir()
                    self.build()
                    path = self.output / "sources/js" / name
                    if path.exists():
                        shutil.rmtree(path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    foreign = self.root / ("foreign-" + self.output.name)
                    foreign.mkdir()
                    (foreign / "keep").write_bytes(b"other owner generated input")
                    before = build.source_inventory(foreign, "go")
                    if mode == "directory-link":
                        path.symlink_to(foreign, target_is_directory=True)
                    elif mode == "dangling-link":
                        path.symlink_to(foreign / "missing", target_is_directory=True)
                    elif mode == "file":
                        path.write_bytes(b"unexpected generated root file")
                    else:
                        os.mkfifo(path)
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    with mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as child:
                        attempt = self.attempt()
                    self.record(path=name, mode=mode, attempt=attempt, subprocess_calls=child.call_count)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("generated source directory", attempt["error"])
                    self.assertEqual(child.call_count, 0)
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(build.source_inventory(foreign, "go"), before)
                    self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                          "build-failure.json": True})

    def test_js_generated_link_blocks_partial_build_and_measurement(self):
        self.build()
        path = self.output / "sources/js/packages/library/dist"
        foreign = self.root / "other-owner-js-dist"
        path.rename(foreign)
        path.symlink_to(foreign, target_is_directory=True)
        before = build.source_inventory(foreign, "go")
        runner = self.probe_run()
        with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire, \
                mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as child:
            attempt = self.attempt(only="js")
        self.record(runner=runner, partial=attempt, acquisition_calls=acquire.call_count,
                    subprocess_calls=child.call_count)
        self.assertEqual(runner["resource_calls"], 0)
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("generated source directory", attempt["error"])
        self.assertEqual(acquire.call_count, 0)
        self.assertEqual(child.call_count, 0)
        self.assertTrue(path.is_symlink())
        self.assertEqual(build.source_inventory(foreign, "go"), before)

    def test_js_generated_directory_external_parent_rejected_by_source_pin(self):
        self.build()
        path = self.output / "sources/js/packages"
        foreign = self.root / "other-owner-js-packages"
        path.rename(foreign)
        path.symlink_to(foreign, target_is_directory=True)
        before = build.source_inventory(foreign, "go")
        with mock.patch.object(build.subprocess, "run", wraps=build.subprocess.run) as child:
            attempt = self.attempt()
        self.record(attempt=attempt, subprocess_calls=child.call_count)
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("source archive mismatch", attempt["error"])
        self.assertEqual(child.call_count, 0)
        self.assertTrue(path.is_symlink())
        self.assertEqual(build.source_inventory(foreign, "go"), before)
        self.assertEqual(attempt["runner"]["resource_calls"], 0)

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


    def test_non_jvm_directory_links_block_build_and_measurement_before_resources(self):
        for language in ("js", "go", "rust"):
            for suffix in ("", "/nested", "/.hidden/nested"):
                with self.subTest(language=language, suffix=suffix), self.copied_entrypoints() as here:
                    self.build()
                    path = here / "drivers" / (language + suffix)
                    foreign = self.root / "other-owner-driver"
                    foreign.mkdir(exist_ok=True)
                    (foreign / "marker.txt").write_bytes(b"other owner input\n")
                    before = build.source_inventory(foreign, "go")
                    if path.exists():
                        path.rename(self.root / "saved-driver")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(foreign, target_is_directory=True)
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    runner = self.probe_run()
                    with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                        attempt = self.attempt()
                    self.record(language=language, suffix=suffix, runner=runner, attempt=attempt,
                                acquisition_calls=acquire.call_count)
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("driver source directory", attempt["error"])
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual(runner["resource_calls"], 0)
                    self.assertEqual(runner["driver_calls"], 0)
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(build.source_inventory(foreign, "go"), before)
                    self.assertTrue(path.is_symlink())
                    path.unlink()
                    shutil.rmtree(here)
                    shutil.rmtree(self.root / "saved-driver", ignore_errors=True)

    def test_non_jvm_directory_link_added_during_acquisition_blocks_children(self):
        with self.copied_entrypoints() as here:
            self.build()
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            classes = build.source_inventory(self.output / "jvm/classes", "go")
            foreign = self.root / "late-other-owner-driver"
            foreign.mkdir()
            (foreign / "marker.txt").write_bytes(b"preserve late driver\n")
            before = build.source_inventory(foreign, "go")
            acquire = build.acquire

            def acquire_then_link(output):
                sources = acquire(output)
                (here / "drivers/js/.late").symlink_to(foreign, target_is_directory=True)
                return sources

            with mock.patch.object(build, "acquire", side_effect=acquire_then_link):
                attempt = self.attempt()
            self.record(attempt=attempt)
            self.assertFalse(attempt["accepted"], attempt)
            self.assertIn("driver source directory", attempt["error"])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
            self.assertEqual(build.source_inventory(foreign, "go"), before)
            self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_existing_non_jvm_file_links_are_fingerprinted_and_remain_usable(self):
        with self.copied_entrypoints() as here:
            names = ("drivers/js/driver.mjs", "drivers/js/runtime-inputs.cjs", "drivers/go/main.go", "drivers/rust/main.rs")
            for index, name in enumerate(names):
                path = here / name
                target = self.root / f"other-owner-file-{index}"
                path.rename(target)
                path.symlink_to(target)
            self.build()
            inputs = json.loads((self.output / "buildinputs.json").read_text())["driver_sources"]
            for name in names:
                self.assertEqual(inputs[name], build.digest(here / name))
                self.assertTrue((here / name).is_symlink())
            self.assertEqual(self.probe_run()["resource_calls"], 1)
            self.record(file_links=names, recorded=inputs)

    def test_metadata_links_preserve_external_bytes_and_record_failure_before_acquisition(self):
        names = ("build-commands.json", "buildinputs.json", "drivers.json", "build-failure.json",
                 "source-inputs.json", "js-runtime-inputs.json", "source-recovery.jsonl")
        for name in names:
            for only in (None, "go"):
                with self.subTest(name=name, only=only):
                    self.build()
                    path = self.output / name
                    external = self.root / "other-owner-metadata.json"
                    contents = path.read_bytes() if path.exists() else b"[]\n"
                    external.write_bytes(contents)
                    path.unlink(missing_ok=True)
                    path.symlink_to(external)
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                        attempt = self.attempt(only=only)
                    self.record(name=name, only=only, attempt=attempt, external=self.file_state(external))
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("build metadata must be a regular file", attempt["error"])
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(external.read_bytes(), contents)
                    self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                           "build-failure.json": True})
                    self.assertFalse((self.output / "build-failure.json").is_symlink())
                    self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    path.unlink(missing_ok=True)
                    self.build()
                    self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_js_rebuild_regenerates_dependencies_and_retains_all_previous_bytes_and_aliases(self):
        self.build()
        source = self.output / "sources/js"
        dependency = source / "node_modules/fixture-dependency/index.js"
        replacement = dependency.with_name(".replacement")
        replacement.write_bytes(b"module.exports = 'modified cached dependency';\n")
        replacement.replace(dependency)
        foreign = self.root / "other-owner-module"
        foreign.mkdir()
        (foreign / "index.js").write_bytes(b"module.exports = 'other owner';\n")
        foreign_before = build.source_inventory(foreign, "go")
        previous = {}
        for name in build.JS_DEPENDENCY_DIRECTORIES:
            root = source / name
            root.mkdir(parents=True, exist_ok=True)
            (root / ".saved-marker").write_bytes(name.encode())
            (root / "other-owner-alias").symlink_to(foreign, target_is_directory=True)
            previous[name] = build.source_inventory(root, "go")
        backups = set(self.output.glob(".js-dependencies-backup-*"))
        self.build()
        created = set(self.output.glob(".js-dependencies-backup-*")) - backups
        self.assertEqual(len(created), 1)
        backup = created.pop()
        for name in build.JS_DEPENDENCY_DIRECTORIES:
            self.assertEqual(build.source_inventory(backup / name, "go"), previous[name])
            self.assertFalse((source / name / ".saved-marker").exists())
        self.assertEqual(build.source_inventory(foreign, "go"), foreign_before)
        self.assertEqual(self.js_value()["value"], "original dependency")
        self.assertEqual(self.probe_run()["resource_calls"], 1)
        self.record(backup=str(backup), previous=previous, foreign_inventory=foreign_before)

    def test_unselected_js_dependency_cache_and_aliases_are_unchanged(self):
        self.build()
        source = self.output / "sources/js"
        for name in build.JS_DEPENDENCY_DIRECTORIES:
            root = source / name
            root.mkdir(parents=True, exist_ok=True)
            (root / ".keep-marker").write_bytes(name.encode())
        before = {name: build.source_inventory(source / name, "go") for name in build.JS_DEPENDENCY_DIRECTORIES}
        backups = set(self.output.glob(".js-dependencies-backup-*"))
        self.build(only="go")
        after = {name: build.source_inventory(source / name, "go") for name in build.JS_DEPENDENCY_DIRECTORIES}
        self.assertEqual(after, before)
        self.assertEqual(set(self.output.glob(".js-dependencies-backup-*")), backups)
        self.record(before=before, after=after)

    def test_gradle_rejects_only_applicable_nonempty_properties_before_acquisition(self):
        with self.copied_entrypoints() as here:
            home = self.root / "selected-gradle-home"
            properties = [home / "gradle.properties", here / "drivers/jvm/gradle.properties",
                          self.root / "gradle.properties"]
            with mock.patch.dict(os.environ, {"GRADLE_USER_HOME": str(home)}):
                for path in properties:
                    for only in (None, "jvm"):
                        with self.subTest(path=str(path), only=only):
                            self.build()
                            path.parent.mkdir(parents=True, exist_ok=True)
                            contents = b"org.gradle.jvmargs=-javaagent:private-unrecorded-agent.jar\n"
                            path.write_bytes(contents)
                            calls = (self.output / "tool-calls.jsonl").read_bytes()
                            classes = build.source_inventory(self.output / "jvm/classes", "go")
                            try:
                                with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                                    attempt = self.attempt(only=only)
                                self.record(path=str(path), only=only, attempt=attempt)
                                self.assertFalse(attempt["accepted"], attempt)
                                self.assertIn("unrecorded Gradle properties", attempt["error"])
                                self.assertNotIn("private-unrecorded-agent", attempt["error"])
                                self.assertEqual(acquire.call_count, 0)
                                self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                                self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                                self.assertEqual(path.read_bytes(), contents)
                            finally:
                                path.unlink()

    def test_gradle_rechecks_late_properties_before_cleanup_and_execution(self):
        home = self.root / "selected-gradle-home"
        with mock.patch.dict(os.environ, {"GRADLE_USER_HOME": str(home)}):
            self.build()
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            classes = build.source_inventory(self.output / "jvm/classes", "go")
            acquire = build.acquire
            path = home / "gradle.properties"

            def acquire_then_add_properties(output):
                sources = acquire(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"org.gradle.jvmargs=-javaagent:late-agent.jar\n")
                return sources

            with mock.patch.object(build, "acquire", side_effect=acquire_then_add_properties):
                attempt = self.attempt()
            self.record(attempt=attempt)
            self.assertFalse(attempt["accepted"], attempt)
            self.assertIn("unrecorded Gradle properties", attempt["error"])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)

    def test_empty_gradle_properties_are_recorded_without_rejecting_unapplied_files(self):
        with self.copied_entrypoints() as here:
            home = self.root / "selected-gradle-home"
            applied = [home / "gradle.properties", here / "drivers/jvm/gradle.properties", self.root / "gradle.properties"]
            for path in applied:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            unrelated = here / "gradle.properties"
            unrelated.write_bytes(b"org.gradle.jvmargs=-javaagent:not-applied.jar\n")
            with mock.patch.dict(os.environ, {"GRADLE_USER_HOME": str(home)}):
                self.build()
                inputs = json.loads((self.output / "buildinputs.json").read_text())["gradle_init_inputs"]
                observed = [dict(row, path=str(Path(row["path"]).resolve())) for row in inputs["properties_files"]]
                self.assertEqual(observed, [{"path": str(path.resolve()), "exists": True, "bytes": 0} for path in applied])
                self.assertEqual(self.probe_run()["resource_calls"], 1)
                self.record(recorded=inputs, unapplied=self.file_state(unrelated))
            for path in applied:
                self.assertEqual(path.read_bytes(), b"")
            self.assertIn(b"not-applied", unrelated.read_bytes())

    def test_unselected_gradle_properties_and_external_link_targets_are_preserved(self):
        home = self.root / "selected-gradle-home"
        with mock.patch.dict(os.environ, {"GRADLE_USER_HOME": str(home)}):
            self.build()
            home.mkdir()
            external = self.root / "other-owner-gradle.properties"
            contents = b"org.gradle.jvmargs=-javaagent:other-owner.jar\n"
            external.write_bytes(contents)
            path = home / "gradle.properties"
            path.symlink_to(external)
            self.build(only="go")
            self.assertEqual(external.read_bytes(), contents)
            calls = (self.output / "tool-calls.jsonl").read_bytes()
            with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                attempt = self.attempt(only="jvm")
            self.assertFalse(attempt["accepted"], attempt)
            self.assertIn("unrecorded Gradle properties", attempt["error"])
            self.assertEqual(acquire.call_count, 0)
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(external.read_bytes(), contents)
            self.assertTrue(path.is_symlink())
            self.record(attempt=attempt, external=self.file_state(external))

    def test_jvm_generated_files_reject_links_and_nonfiles_before_acquisition(self):
        for name in ("classpath.txt", "dependencies.txt"):
            for only in (None, "jvm"):
                for kind in ("external-link", "dangling-link", "directory"):
                    with self.subTest(name=name, only=only, kind=kind):
                        self.build()
                        path = self.output / "jvm" / name
                        contents = path.read_bytes() if path.exists() else b"other owner bytes\x00\xff"
                        external = self.root / "other-owner-jvm-file"
                        external.write_bytes(contents)
                        path.unlink(missing_ok=True)
                        if kind == "directory":
                            path.mkdir()
                        else:
                            path.symlink_to(external if kind == "external-link" else self.root / f"missing-jvm-file-{name}-{only}")
                        calls = (self.output / "tool-calls.jsonl").read_bytes()
                        classes = build.source_inventory(self.output / "jvm/classes", "go")
                        try:
                            with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                                attempt = self.attempt(only=only)
                            self.record(name=name, only=only, kind=kind, attempt=attempt, external=self.file_state(external))
                            self.assertFalse(attempt["accepted"], attempt)
                            self.assertIn("JVM output file must be a regular file inside output", attempt["error"])
                            self.assertEqual(acquire.call_count, 0)
                            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                            self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                            self.assertEqual(external.read_bytes(), contents)
                            self.assertEqual(attempt["runner"]["resource_calls"], 0)
                        finally:
                            if kind == "directory":
                                path.rmdir()
                            else:
                                path.unlink()

    def test_jvm_generated_files_added_during_acquisition_preserve_classes_and_external_bytes(self):
        for name in ("classpath.txt", "dependencies.txt"):
            with self.subTest(name=name):
                self.build()
                calls = (self.output / "tool-calls.jsonl").read_bytes()
                classes = build.source_inventory(self.output / "jvm/classes", "go")
                path = self.output / "jvm" / name
                external = self.root / "late-jvm-file"
                contents = b"late other owner bytes\x00\xff"
                external.write_bytes(contents)
                acquire = build.acquire

                def acquire_then_link(output):
                    sources = acquire(output)
                    path.unlink(missing_ok=True)
                    path.symlink_to(external)
                    return sources

                try:
                    with mock.patch.object(build, "acquire", side_effect=acquire_then_link):
                        attempt = self.attempt()
                    self.record(name=name, attempt=attempt, external=self.file_state(external))
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("JVM output file must be a regular file inside output", attempt["error"])
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                    self.assertEqual(external.read_bytes(), contents)
                    self.assertTrue(path.is_symlink())
                finally:
                    path.unlink()

    def test_dynamic_diagnostic_links_reject_before_their_child_on_full_and_partial_builds(self):
        for label, suffix, selected in (("jvm", ".log", "jvm"), ("rust-inputs", ".log", "rust"),
                                         ("rust-inputs", ".stdout", "rust")):
            for only in (None, selected):
                with self.subTest(label=label, suffix=suffix, only=only):
                    self.build()
                    commands = json.loads((self.output / "build-commands.json").read_text())
                    attempt_number = 1 + sum(row["label"] == label for row in commands)
                    path = self.output / f"build-{label}-{attempt_number}{suffix}"
                    external = self.root / "other-owner-diagnostic"
                    contents = b"other owner diagnostic bytes\x00\xff"
                    external.write_bytes(contents)
                    path.symlink_to(external)
                    calls = len((self.output / "tool-calls.jsonl").read_text().splitlines())
                    try:
                        attempt = self.attempt(only=only)
                        new_calls = [json.loads(line) for line in (self.output / "tool-calls.jsonl").read_text().splitlines()[calls:]]
                        self.record(label=label, suffix=suffix, only=only, attempt=attempt, new_calls=new_calls,
                                    external=self.file_state(external))
                        self.assertFalse(attempt["accepted"], attempt)
                        self.assertIn("build diagnostic must be a regular file inside output", attempt["error"])
                        self.assertFalse(any(row["tool"] == "gradle" if label == "jvm" else
                                             row["tool"] == "cargo" and row["args"][0] == "metadata" for row in new_calls))
                        self.assertEqual(external.read_bytes(), contents)
                        self.assertTrue(path.is_symlink())
                        self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                               "build-failure.json": True})
                        self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    finally:
                        path.unlink()

    def test_dynamic_diagnostic_rejection_allows_retry_without_losing_previous_command_results(self):
        self.build()
        commands = json.loads((self.output / "build-commands.json").read_text())
        attempt_number = 1 + sum(row["label"] == "jvm" for row in commands)
        path = self.output / f"build-jvm-{attempt_number}.log"
        path.mkdir()
        attempt = self.attempt(only="jvm")
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("build diagnostic must be a regular file inside output", attempt["error"])
        self.assertEqual(json.loads((self.output / "build-commands.json").read_text()), commands)
        path.rmdir()
        self.build()
        rows = json.loads((self.output / "build-commands.json").read_text())
        self.assertEqual(rows[:len(commands)], commands)
        self.assertTrue(all(row["exit"] == 0 for row in rows[len(commands):]))
        self.assertEqual(self.probe_run()["resource_calls"], 1)
        self.record(attempt=attempt, previous_commands=commands, retry_commands=rows[len(commands):])

    def test_pnpm_install_build_and_record_exclude_hooks_and_preserve_parent_settings(self):
        hook = self.root / "external-global-hook.cjs"
        marker = self.root / "external-hook-marker"
        hook.write_text("require('node:fs').appendFileSync(process.env.INTEROP_TEST_HOOK_MARKER, 'loaded\\n');\n")
        userconfig = self.root / "dedicated.npmrc"
        userconfig.write_text(f"global-pnpmfile={hook}\n")
        executable = self.bin / "pnpm"
        original = executable.read_text()
        executable.write_text(original.split("\n", 1)[0] + "\n" + '''
import os, subprocess, sys
if os.environ.get("PNPM_CONFIG_GLOBAL_PNPMFILE") and "--ignore-pnpmfile" not in sys.argv and os.environ.get("PNPM_CONFIG_IGNORE_PNPMFILE") != "true":
    subprocess.run(["node", os.environ["PNPM_CONFIG_GLOBAL_PNPMFILE"]], check=True)
''' + original.split("\n", 1)[1])
        environment = {"PNPM_CONFIG_GLOBAL_PNPMFILE": str(hook), "NPM_CONFIG_USERCONFIG": str(userconfig),
                       "INTEROP_TEST_HOOK_MARKER": str(marker), "PNPM_CONFIG_IGNORE_PNPMFILE": "false",
                       "pnpm_config_ignore_pnpmfile": "false", "pnpm_config_ignorePnpmfile": "false"}
        files = {path: self.file_state(path) for path in (hook, userconfig)}
        observed = []
        execute = subprocess.run

        def capture(command, *args, **kwargs):
            if Path(str(command[0])).name == "pnpm":
                observed.append({"argv": list(map(str, command)), "environment": {name: kwargs["env"].get(name)
                                 for name in environment if "IGNORE" in name or "ignore" in name}})
            return execute(command, *args, **kwargs)

        with mock.patch.dict(os.environ, environment), mock.patch.object(build.subprocess, "run", side_effect=capture):
            self.build()
            self.build(only="js")
            self.assertTrue(all(os.environ[name] == value for name, value in environment.items()))
        self.assertFalse(marker.exists())
        self.assertEqual(files, {path: self.file_state(path) for path in files})
        self.assertEqual(len(observed), 4)
        self.assertTrue(all("--ignore-pnpmfile" in row["argv"] and set(row["environment"].values()) == {"true"} for row in observed))
        inputs = json.loads((self.output / "buildinputs.json").read_text())
        self.assertEqual(inputs["pnpm_hook_settings"], {"ignore_pnpmfile": True, "arguments": ["--ignore-pnpmfile"],
                         "environment": {name: "true" for name in environment if "IGNORE" in name or "ignore" in name}})
        self.assertEqual(self.probe_run()["resource_calls"], 1)
        self.record(commands=observed, recorded=inputs["pnpm_hook_settings"], marker_exists=marker.exists())

    def test_build_rejects_resolved_classpath_separator_before_side_effects(self):
        target = self.root / ("classpath" + os.pathsep + "output")
        existing = self.root / ("existing" + os.pathsep + "output")
        existing.mkdir()
        (existing / "keep").write_bytes(b"other owner data")
        alias = self.root / "classpath-alias"
        alias.symlink_to(existing, target_is_directory=True)
        for output in (target, existing, alias):
            for only in (None, "jvm", "go", "rust", "js"):
                with self.subTest(output=str(output), only=only):
                    self.output = output
                    before = build.source_inventory(existing, "go")
                    with mock.patch.object(build, "acquire") as acquire, \
                            mock.patch.object(build.subprocess, "run") as child:
                        with self.assertRaisesRegex(RuntimeError, "Java classpath separator"):
                            self.build(only=only)
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual(child.call_count, 0)
                    self.assertFalse(target.exists())
                    self.assertEqual(build.source_inventory(existing, "go"), before)
                    self.record(output=str(output), only=only, acquisition_calls=acquire.call_count,
                                subprocess_calls=child.call_count, missing_output_preserved=not target.exists(),
                                existing_output_preserved=True)

    def test_run_rejects_resolved_classpath_separator_before_resources(self):
        target = self.root / ("result" + os.pathsep + "output")
        existing = self.root / ("existing-result" + os.pathsep + "output")
        existing.mkdir()
        (existing / "keep").write_bytes(b"other owner result")
        alias = self.root / "result-alias"
        alias.symlink_to(existing, target_is_directory=True)
        for output in (target, existing, alias):
            with self.subTest(output=str(output)):
                before = build.source_inventory(existing, "go")
                argv = ["run.py", "--build", str(self.output), "--output", str(output)]
                with mock.patch.object(sys, "argv", argv), mock.patch.object(run, "verify_artifacts") as verify, \
                        mock.patch.object(run, "Local") as local, mock.patch.object(run, "Driver") as driver:
                    with self.assertRaisesRegex(RuntimeError, "Java classpath separator"):
                        run.main()
                self.assertEqual(verify.call_count, 0)
                self.assertEqual(local.call_count, 0)
                self.assertEqual(driver.call_count, 0)
                self.assertFalse(target.exists())
                self.assertEqual(build.source_inventory(existing, "go"), before)
                self.record(output=str(output), artifact_verification_calls=verify.call_count,
                            resource_calls=local.call_count, driver_calls=driver.call_count,
                            missing_output_preserved=not target.exists(), existing_output_preserved=True)

    def test_pnpm_virtual_store_is_owned_and_preserves_inherited_paths_and_backups(self):
        executable = self.bin / "pnpm"
        original = executable.read_text()
        executable.write_text(original.split("\n", 1)[0] + "\n" + '''
import os, sys
from pathlib import Path
output = Path(os.environ["INTEROP_TEST_OUTPUT"])
if "install" in sys.argv:
    store = Path(sys.argv[sys.argv.index("--virtual-store-dir") + 1] if "--virtual-store-dir" in sys.argv else
        os.environ.get("PNPM_CONFIG_VIRTUAL_STORE_DIR") or os.environ["pnpm_config_virtual_store_dir"])
    store.mkdir(parents=True, exist_ok=True)
    (output / "observed-virtual-store.txt").write_text(str(store))
''' + original.split("\n", 1)[1].replace('output / "sources/js/node_modules/fixture-dependency"',
                                        'Path((output / "observed-virtual-store.txt").read_text()) / "fixture-dependency"'))
        for index, name in enumerate(("PNPM_CONFIG_VIRTUAL_STORE_DIR", "pnpm_config_virtual_store_dir")):
            with self.subTest(setting=name):
                external = self.root / (str(index) + "-external")
                external.mkdir()
                (external / "keep").write_bytes(b"external virtual store data")
                before = build.source_inventory(external, "go")
                with mock.patch.dict(os.environ, {name: str(external)}):
                    self.build()
                    first = json.loads((self.output / "buildinputs.json").read_text())
                    node_modules = self.output / "sources/js/node_modules"
                    previous = build.source_inventory(node_modules, "go")
                    backups = set(self.output.glob(".js-dependencies-backup-*"))
                    self.build(only="js")
                    self.assertEqual(os.environ[name], str(external))
                current = json.loads((self.output / "buildinputs.json").read_text())
                store = (node_modules / ".pnpm").resolve()
                self.assertEqual(current["pnpm_virtual_store_dir"], str(store))
                self.assertEqual((self.output / "observed-virtual-store.txt").read_text(), str(store))
                self.assertTrue(store.is_relative_to(self.output.resolve()))
                self.assertEqual(build.source_inventory(external, "go"), before)
                new_backups = set(self.output.glob(".js-dependencies-backup-*")) - backups
                self.assertEqual(len(new_backups), 1)
                self.assertEqual(build.source_inventory(next(iter(new_backups)) / "node_modules", "go"), previous)
                unchanged = [row for row in first["artifacts"] if not Path(row["path"]).is_relative_to(
                    (self.output / "sources/js").resolve()) and row["path"] != first["js_runtime_inputs"]]
                self.assertTrue(all(row in current["artifacts"] for row in unchanged))
                runtime = json.loads((self.output / "js-runtime-inputs.json").read_text())
                self.assertTrue(any(Path(row["path"]).is_relative_to(store) for row in runtime["files"]))
                self.assertEqual(self.probe_run()["resource_calls"], 1)
                self.record(setting=name, virtual_store=str(store), external_preserved=True,
                            backup_preserved=True, unselected_artifacts=len(unchanged), runtime_inputs=runtime)

    def test_unselected_partial_build_preserves_recorded_pnpm_virtual_store(self):
        self.build()
        previous = json.loads((self.output / "buildinputs.json").read_text())["pnpm_virtual_store_dir"]
        with mock.patch.dict(os.environ, {"PNPM_CONFIG_VIRTUAL_STORE_DIR": str(self.root / "unselected-external")}):
            self.build(only="go")
        current = json.loads((self.output / "buildinputs.json").read_text())["pnpm_virtual_store_dir"]
        self.assertEqual(current, previous)
        self.assertEqual(self.probe_run()["resource_calls"], 1)
        self.record(previous=previous, current=current)

    def test_unselected_partial_build_preserves_recorded_pnpm_hook_settings(self):
        self.build()
        previous = json.loads((self.output / "buildinputs.json").read_text())["pnpm_hook_settings"]
        with mock.patch.dict(os.environ, {"PNPM_CONFIG_GLOBAL_PNPMFILE": str(self.root / "unselected-hook.cjs")}):
            self.build(only="go")
        current = json.loads((self.output / "buildinputs.json").read_text())["pnpm_hook_settings"]
        self.assertEqual(current, previous)
        self.assertEqual(self.probe_run()["resource_calls"], 1)
        self.record(previous=previous, current=current)


    def test_go_cached_dependency_verification_precedes_compile_and_records_failure(self):
        go = self.bin / "go"
        go.write_text(go.read_text() + '''
if tool == "go" and args == ["mod", "verify"]:
    if (output / "fail-go-verify").exists():
        print("cached dependency dir has been modified", file=sys.stderr)
        raise SystemExit(31)
    print("all modules verified")
''')
        cache = self.root / "dedicated-go-cache"
        cache.mkdir()
        dependency = cache / "dependency.go"
        dependency.write_bytes(b"dedicated modified dependency\x00\xff")
        environment = {"GOMODCACHE": str(cache), "GOCACHE": str(self.root / "dedicated-go-build-cache")}
        for only in (None, "go"):
            with self.subTest(only=only), mock.patch.dict(os.environ, environment):
                (self.output / "fail-go-verify").unlink(missing_ok=True)
                self.build()
                self.build(only="go")
                commands = json.loads((self.output / "build-commands.json").read_text())
                self.assertEqual([row["label"] for row in commands[-3:]], ["go-verify", "go", "go-inputs"])
                count = len(commands)
                other = {str(path): self.file_state(path) for path in
                         (self.output / "rust-driver/target/debug/interop-driver",
                          self.output / "sources/js/packages/library/dist/index.js")}
                (self.output / "fail-go-verify").write_text("reject before compilation")
                before = dependency.read_bytes()
                attempt = self.attempt(only=only)
                latest = json.loads((self.output / "build-commands.json").read_text())[count:]
                self.assertFalse(attempt["accepted"], attempt)
                self.assertEqual([row["label"] for row in latest], ["jvm", "go-verify"] if only is None else ["go-verify"])
                self.assertEqual(latest[-1]["argv"], ["go", "mod", "verify"])
                self.assertEqual(latest[-1]["exit"], 31)
                self.assertEqual(dependency.read_bytes(), before)
                self.assertEqual(os.environ["GOMODCACHE"], str(cache))
                self.assertEqual(other, {path: self.file_state(Path(path)) for path in other})
                self.assertEqual(attempt["runner"]["resource_calls"], 0)
                self.assertFalse(attempt["metadata"]["drivers.json"])
                self.assertFalse(attempt["metadata"]["buildinputs.json"])
                self.record(only=only, attempt=attempt, actual_commands=latest, cache=self.file_state(dependency))

    def test_jvm_work_tree_links_and_non_directories_reject_before_acquisition(self):
        for name in ("tmp", "kotlin", "generated", "reports"):
            for only in (None, "jvm"):
                for kind in ("root-link", "root-file", "nested-directory-link", "nested-file-link", "dangling-file-link"):
                    with self.subTest(name=name, only=only, kind=kind):
                        self.build()
                        root = self.output / "jvm" / name
                        external = self.root / f"external-{name}-{only}-{kind}"
                        external.mkdir()
                        (external / "state").write_bytes(b"other owner initial bytes\x00\xff")
                        if root.exists():
                            shutil.rmtree(root)
                        if kind == "root-file":
                            root.write_bytes(b"unknown existing file")
                            linked = root
                        elif kind == "root-link":
                            root.symlink_to(external, target_is_directory=True)
                            linked = root
                        else:
                            root.mkdir()
                            linked = root / "task" / "state"
                            linked.parent.mkdir()
                            linked.symlink_to(external if kind == "nested-directory-link" else
                                              self.root / "missing-work-file" if kind == "dangling-file-link" else external / "state",
                                              target_is_directory=kind == "nested-directory-link")
                        foreign = build.source_inventory(external, "go")
                        classes = build.source_inventory(self.output / "jvm/classes", "go")
                        calls = (self.output / "tool-calls.jsonl").read_bytes()
                        try:
                            with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                                attempt = self.attempt(only=only)
                            self.assertFalse(attempt["accepted"], attempt)
                            self.assertIn("JVM", attempt["error"])
                            self.assertEqual(acquire.call_count, 0)
                            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                            self.assertEqual(build.source_inventory(external, "go"), foreign)
                            self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                            self.assertEqual(attempt["runner"]["resource_calls"], 0)
                            self.record(name=name, only=only, kind=kind, attempt=attempt, external=foreign)
                        finally:
                            linked.unlink()
                            if root.exists():
                                shutil.rmtree(root)

    def test_jvm_work_links_added_during_acquisition_preserve_classes_and_external_bytes(self):
        for relative in ("tmp", "kotlin/compileKotlin/cacheable/last-build.bin",
                         "generated/sources/annotationProcessor/java/main/foreign", "reports/problems/report.html"):
            with self.subTest(relative=relative):
                self.build()
                path = self.output / "jvm" / relative
                external = self.root / ("late-" + relative.replace("/", "-"))
                external.write_bytes(b"late other owner bytes\x00\xff")
                calls = (self.output / "tool-calls.jsonl").read_bytes()
                classes = build.source_inventory(self.output / "jvm/classes", "go")
                acquire = build.acquire

                def acquire_then_link(output):
                    result = acquire(output)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(external)
                    return result

                try:
                    with mock.patch.object(build, "acquire", side_effect=acquire_then_link):
                        attempt = self.attempt()
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("JVM", attempt["error"])
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                    self.assertEqual(external.read_bytes(), b"late other owner bytes\x00\xff")
                    self.assertTrue(path.is_symlink())
                    self.record(relative=relative, attempt=attempt, external=self.file_state(external))
                finally:
                    path.unlink()

    def test_jvm_work_links_added_after_cleanup_reject_before_gradle_child(self):
        self.build()
        path = self.output / "jvm/tmp/compileJava/previous-compilation-data.bin"
        path.parent.mkdir(parents=True)
        external = self.root / "after-cleanup-external-state"
        external.write_bytes(b"preserve external work state\x00\xff")
        calls = (self.output / "tool-calls.jsonl").read_bytes()
        cleanup = shutil.rmtree

        def clean_then_link(root, *args, **kwargs):
            cleanup(root, *args, **kwargs)
            if root == self.output.resolve() / "jvm/classes":
                path.symlink_to(external)

        try:
            with mock.patch.object(build.shutil, "rmtree", side_effect=clean_then_link):
                attempt = self.attempt(only="jvm")
            self.assertFalse(attempt["accepted"], attempt)
            self.assertIn("JVM", attempt["error"])
            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
            self.assertEqual(external.read_bytes(), b"preserve external work state\x00\xff")
            self.assertTrue(path.is_symlink())
            self.assertEqual(attempt["runner"]["resource_calls"], 0)
            self.record(attempt=attempt, external=self.file_state(external))
        finally:
            path.unlink()

    def test_jvm_regular_work_trees_and_unselected_links_preserve_owner_files(self):
        self.build()
        kept = []
        for name in ("tmp/compileJava/state", "kotlin/compileKotlin/state", "generated/sources/state",
                     "reports/problems/state", "user-resource", "../gradle-cache/keep"):
            path = self.output / "jvm" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"owner work file\x00\xff")
            kept.append(path)
        before = {str(path): self.file_state(path) for path in kept}
        for only in (None, "jvm"):
            self.build(only=only)
            self.assertEqual(before, {str(path): self.file_state(path) for path in kept})
            self.assertEqual(self.probe_run()["resource_calls"], 1)
        path = self.output / "jvm/tmp/compileJava/unselected-link"
        external = self.root / "unselected-external-state"
        external.write_bytes(b"unselected other owner bytes")
        path.symlink_to(external)
        self.build(only="go")
        self.assertTrue(path.is_symlink())
        self.assertEqual(external.read_bytes(), b"unselected other owner bytes")
        self.assertEqual(before, {str(path): self.file_state(path) for path in kept})
        self.record(kept=before, unselected_link=str(path), external=self.file_state(external))


    def test_missing_source_recovery_retains_complete_original_cache(self):
        self.build()
        source = (self.output / "sources/js").resolve()
        generated = source / "node_modules/retained"
        generated.mkdir()
        contents = b"retained dependency and binary bytes\x00\xff"
        (generated / "binary").write_bytes(contents)
        (generated / "internal-link").symlink_to("binary")
        external = self.root / "external-cache-alias"
        external.symlink_to(generated / "binary")
        link = os.readlink(external)
        (source / "marker.txt").unlink()
        before = build.source_inventory(source, "go")
        dependencies = (source / "node_modules/retained/binary").stat()
        acquire = build.acquire
        downloads = self.build()
        records = [json.loads(row) for row in (self.output / "source-recovery.jsonl").read_text().splitlines()]
        recovered = [row for row in records if row.get("language") == "js" and
                     row.get("kind") == "directory" and row.get("phase") == "acquired"][-1]
        backup = Path(recovered["backup_path"]) if "backup_path" in recovered else self.output / "missing-backup"
        self.record(recovery=recovered, original_inventory=before, backup_exists=backup.is_dir())
        self.assertEqual(downloads, 0)
        self.assertTrue(backup.is_dir(), recovered)
        self.assertEqual(backup.parent.parent, self.output.resolve())
        self.assertEqual(build.source_inventory(backup, "go"), before)
        self.assertEqual((backup / "node_modules/retained/binary").read_bytes(), contents)
        self.assertEqual((backup / "node_modules/retained/internal-link").read_bytes(), contents)
        self.assertEqual((backup / "node_modules/retained/binary").stat().st_ino, dependencies.st_ino)
        self.assertEqual(os.readlink(external), link)
        self.assertEqual((source / "marker.txt").read_text(), self.pins["sources"]["js"])
        with mock.patch.object(build, "PINS", self.pins):
            acquire(self.output)
        self.assertEqual(build.source_inventory(backup, "go"), before)
        self.assertEqual(self.probe_run()["resource_calls"], 1)

    def test_missing_source_candidate_placement_failure_restores_original_cache(self):
        self.build()
        source = (self.output / "sources/js").resolve()
        (source / "marker.txt").unlink()
        before = build.source_inventory(source, "go")
        inode = source.stat().st_ino
        alias = os.readlink(self.output / "sources/js")
        previous_rows = len((self.output / "source-recovery.jsonl").read_text().splitlines())
        rename = Path.rename

        def fail_candidate(path, target):
            if path.name == source.name and path.parent.name.startswith(".js-extract-") and Path(target) == source:
                raise OSError("fixture candidate placement failure")
            return rename(path, target)

        with mock.patch.object(Path, "rename", fail_candidate):
            attempt = self.attempt()
        rows = [json.loads(row) for row in (self.output / "source-recovery.jsonl").read_text().splitlines()[previous_rows:]]
        self.record(attempt=attempt, recovery=rows, original_inventory=before, inode_before=inode,
                    inode_after=source.stat().st_ino)
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("fixture candidate placement failure", attempt["error"])
        self.assertEqual(build.source_inventory(source, "go"), before)
        self.assertEqual(source.stat().st_ino, inode)
        self.assertEqual(os.readlink(self.output / "sources/js"), alias)
        self.assertFalse(any(row.get("language") == "js" and row.get("phase") == "acquired" for row in rows))
        self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                               "build-failure.json": True})
        self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_unselected_missing_js_source_preserves_cache_before_rejection(self):
        self.build()
        source = (self.output / "sources/js").resolve()
        (source / "marker.txt").unlink()
        before = build.source_inventory(source, "go")
        calls = (self.output / "tool-calls.jsonl").read_bytes()
        alias = os.readlink(self.output / "sources/js")
        attempt = self.attempt(only="go")
        self.record(attempt=attempt, original_inventory=before)
        self.assertFalse(attempt["accepted"], attempt)
        self.assertIn("source inventory mismatch", attempt["error"])
        self.assertEqual(build.source_inventory(source, "go"), before)
        self.assertEqual(os.readlink(self.output / "sources/js"), alias)
        self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
        self.assertEqual(attempt["runner"]["resource_calls"], 0)

    def test_dynamic_diagnostic_hardlinks_reject_before_child_and_preserve_inode(self):
        for label, suffix, selected in (("jvm", ".log", "jvm"), ("rust-inputs", ".log", "rust"),
                                         ("rust-inputs", ".stdout", "rust")):
            for only in (None, selected):
                with self.subTest(label=label, suffix=suffix, only=only):
                    self.build()
                    commands = json.loads((self.output / "build-commands.json").read_text())
                    attempt_number = 1 + sum(row["label"] == label for row in commands)
                    path = self.output / f"build-{label}-{attempt_number}{suffix}"
                    external = self.root / "external-hardlink-sample"
                    contents = b"original shared diagnostic inode bytes\x00\xff"
                    external.write_bytes(contents)
                    os.link(external, path)
                    before = external.stat()
                    calls = len((self.output / "tool-calls.jsonl").read_text().splitlines())
                    try:
                        attempt = self.attempt(only=only)
                        new_calls = [json.loads(row) for row in
                                     (self.output / "tool-calls.jsonl").read_text().splitlines()[calls:]]
                        self.record(label=label, suffix=suffix, only=only, attempt=attempt, new_calls=new_calls,
                                    external=self.file_state(external), diagnostic=self.file_state(path),
                                    inode_before={"device": before.st_dev, "inode": before.st_ino, "links": before.st_nlink},
                                    inode_after={str(name): {"device": name.stat().st_dev, "inode": name.stat().st_ino,
                                                 "links": name.stat().st_nlink} for name in (external, path)})
                        self.assertFalse(attempt["accepted"], attempt)
                        self.assertIn("build diagnostic must not have multiple hard links", attempt["error"])
                        self.assertFalse(any(row["tool"] == "gradle" if label == "jvm" else
                                             row["tool"] == "cargo" and row["args"][0] == "metadata"
                                             for row in new_calls))
                        for name in (external, path):
                            self.assertEqual(name.read_bytes(), contents)
                            self.assertEqual((name.stat().st_dev, name.stat().st_ino, name.stat().st_nlink),
                                             (before.st_dev, before.st_ino, 2))
                        self.assertEqual(json.loads((self.output / "build-commands.json").read_text())[:len(commands)], commands)
                        self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                               "build-failure.json": True})
                        self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    finally:
                        path.unlink()


    def test_jvm_text_hardlinks_reject_before_acquisition_and_preserve_inode(self):
        for name in ("classpath.txt", "dependencies.txt"):
            for only in (None, "jvm"):
                with self.subTest(name=name, only=only):
                    self.build()
                    path = self.output / "jvm" / name
                    contents = b"original JVM listing bytes\x00\xff"
                    external = self.root / "external-jvm-listing"
                    external.write_bytes(contents)
                    path.unlink(missing_ok=True)
                    os.link(external, path)
                    before = external.stat()
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    classes = build.source_inventory(self.output / "jvm/classes", "go")
                    try:
                        with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                            attempt = self.attempt(only=only)
                        self.record(name=name, only=only, stage="before-acquisition", attempt=attempt,
                                    acquire_calls=acquire.call_count, child_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == calls,
                                    contents_hex=contents.hex(),
                                    files={str(p): dict(self.file_state(p), contents_hex=p.read_bytes().hex(),
                                             device=p.stat().st_dev, inode=p.stat().st_ino, links=p.stat().st_nlink)
                                           for p in (external, path)},
                                    inode_before={"device": before.st_dev, "inode": before.st_ino, "links": before.st_nlink})
                        self.assertFalse(attempt["accepted"], attempt)
                        self.assertIn("JVM output file must not have multiple hard links", attempt["error"])
                        self.assertEqual(acquire.call_count, 0)
                        self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                        self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                        for p in (external, path):
                            self.assertEqual(p.read_bytes(), contents)
                            self.assertEqual((p.stat().st_dev, p.stat().st_ino, p.stat().st_nlink),
                                             (before.st_dev, before.st_ino, 2))
                        self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                               "build-failure.json": True})
                        self.assertEqual(attempt["runner"]["resource_calls"], 0)
                        self.assertEqual(attempt["runner"]["driver_calls"], 0)
                    finally:
                        path.unlink()

    def test_jvm_text_hardlinks_recheck_before_cleanup_and_gradle(self):
        for name in ("classpath.txt", "dependencies.txt"):
            for only in (None, "jvm"):
                for stage in ("after-acquisition", "after-cleanup"):
                    with self.subTest(name=name, only=only, stage=stage):
                        self.build()
                        path = self.output / "jvm" / name
                        contents = b"late JVM listing bytes\x00\xff"
                        external = self.root / "late-external-jvm-listing"
                        external.write_bytes(contents)
                        calls = (self.output / "tool-calls.jsonl").read_bytes()
                        classes = build.source_inventory(self.output / "jvm/classes", "go")
                        acquire, remove = build.acquire, shutil.rmtree

                        def link():
                            path.unlink(missing_ok=True)
                            os.link(external, path)

                        def acquire_then_link(output):
                            result = acquire(output)
                            if stage == "after-acquisition":
                                link()
                            return result

                        def remove_then_link(tree, *args, **kwargs):
                            result = remove(tree, *args, **kwargs)
                            if stage == "after-cleanup" and Path(tree).resolve() == (self.output / "jvm/classes").resolve():
                                link()
                            return result

                        before = external.stat()
                        try:
                            with mock.patch.object(build, "acquire", side_effect=acquire_then_link), \
                                    mock.patch.object(shutil, "rmtree", side_effect=remove_then_link):
                                attempt = self.attempt(only=only)
                            self.record(name=name, only=only, stage=stage, attempt=attempt, contents_hex=contents.hex(),
                                        child_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == calls,
                                        files={str(p): dict(self.file_state(p), contents_hex=p.read_bytes().hex(),
                                                 device=p.stat().st_dev, inode=p.stat().st_ino, links=p.stat().st_nlink)
                                               for p in (external, path)},
                                        inode_before={"device": before.st_dev, "inode": before.st_ino, "links": 2})
                            self.assertFalse(attempt["accepted"], attempt)
                            self.assertIn("JVM output file must not have multiple hard links", attempt["error"])
                            self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                            if stage == "after-acquisition":
                                self.assertEqual(build.source_inventory(self.output / "jvm/classes", "go"), classes)
                            for p in (external, path):
                                self.assertEqual(p.read_bytes(), contents)
                                self.assertEqual((p.stat().st_dev, p.stat().st_ino, p.stat().st_nlink),
                                                 (before.st_dev, before.st_ino, 2))
                            self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                                   "build-failure.json": True})
                            self.assertEqual(attempt["runner"]["resource_calls"], 0)
                            self.assertEqual(attempt["runner"]["driver_calls"], 0)
                        finally:
                            path.unlink(missing_ok=True)

    def test_source_recovery_hardlinks_reject_before_acquisition_and_preserve_inode(self):
        for only in (None, "js"):
            with self.subTest(only=only):
                self.build()
                if only is None:
                    (self.output / "sources/js/marker.txt").unlink()
                path = self.output / "source-recovery.jsonl"
                contents = path.read_bytes() if path.exists() else b'{"original":"recovery bytes"}\n'
                external = self.root / "external-source-recovery"
                external.write_bytes(contents)
                path.unlink(missing_ok=True)
                os.link(external, path)
                before = external.stat()
                calls = (self.output / "tool-calls.jsonl").read_bytes()
                inventory = build.source_inventory(self.output / "sources/js", "js")
                try:
                    with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                        attempt = self.attempt(only=only)
                    self.record(only=only, stage="before-acquisition", attempt=attempt, acquire_calls=acquire.call_count,
                                child_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == calls,
                                contents_hex=contents.hex(),
                                files={str(p): dict(self.file_state(p), contents_hex=p.read_bytes().hex(),
                                         device=p.stat().st_dev, inode=p.stat().st_ino, links=p.stat().st_nlink)
                                       for p in (external, path)},
                                inode_before={"device": before.st_dev, "inode": before.st_ino, "links": before.st_nlink})
                    self.assertFalse(attempt["accepted"], attempt)
                    self.assertIn("source recovery log must not have multiple hard links", attempt["error"])
                    self.assertEqual(acquire.call_count, 0)
                    self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                    self.assertEqual(build.source_inventory(self.output / "sources/js", "js"), inventory)
                    for p in (external, path):
                        self.assertEqual(p.read_bytes(), contents)
                        self.assertEqual((p.stat().st_dev, p.stat().st_ino, p.stat().st_nlink),
                                         (before.st_dev, before.st_ino, 2))
                    self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                           "build-failure.json": True})
                    self.assertEqual(attempt["runner"]["resource_calls"], 0)
                    self.assertEqual(attempt["runner"]["driver_calls"], 0)
                finally:
                    path.unlink()

    def test_source_recovery_hardlinks_reject_direct_append_and_preserve_inode(self):
        path = self.output / "source-recovery.jsonl"
        external = self.root / "external-direct-recovery"
        contents = b'{"original":"recovery bytes"}\n'
        external.write_bytes(contents)
        os.link(external, path)
        before = external.stat()
        with self.assertRaisesRegex(RuntimeError, "source recovery log must not have multiple hard links"):
            build.source_recovery(self.output, phase="incomplete", kind="archive")
        self.record(stage="direct-append", contents_hex=contents.hex(),
                    files={str(p): dict(self.file_state(p), contents_hex=p.read_bytes().hex(),
                             device=p.stat().st_dev, inode=p.stat().st_ino, links=p.stat().st_nlink)
                           for p in (external, path)},
                    inode_before={"device": before.st_dev, "inode": before.st_ino, "links": before.st_nlink})
        for p in (external, path):
            self.assertEqual(p.read_bytes(), contents)
            self.assertEqual((p.stat().st_dev, p.stat().st_ino, p.stat().st_nlink),
                             (before.st_dev, before.st_ino, 2))

    def test_js_negative_timestamp_conversion_matches_existing_floor_precision(self):
        nanos = [-1, -999999, -1000001, -1000000, -2000000, 0, 1, 999999, 1000001]
        script = """
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const transformation = source.slice(source.indexOf('const unwrap ='), source.indexOf('const categories ='));
const observed = JSON.parse(process.argv[2]).map(nanos => {
  const input = { type_name: 'pure', value: 'timestamp', seq_nr: 1, occurred_at_ns: nanos,
                  manifest: 'pure conversion', payload: { value: 1 } };
  const value = vm.runInNewContext(transformation + '\\nobservedEvent(event(input));', {
    input, AggregateId: { of: () => ({ type: 'ok', value: 'pure-timestamp' }),
                         asString: value => ({ type: 'ok', value }) },
    EventEnvelope: { create: value => ({ type: 'ok', value }) },
  });
  return { input_ns: nanos, observed_ns: value.occurred_at_ns };
});
console.log(JSON.stringify(observed));
"""
        result = subprocess.run(["node", "-e", script, str(build.HERE / "drivers/js/driver.mjs"),
                                 json.dumps([str(value) for value in nanos])],
                                capture_output=True, text=True, env=build.child_environment())
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        expected = [{"input_ns": str(value), "observed_ns": str(value // 1_000_000 * 1_000_000)} for value in nanos]
        self.record(kind="pure-current-driver-transformation", observed=observed, expected=expected)
        self.assertEqual(observed, expected)

    def test_generated_package_hardlinks_reject_before_acquisition_and_preserve_both_names(self):
        targets = (("go-driver/main.go", "go"), ("go-driver/go.mod", "go"),
                   ("go-driver/go.sum", "go"), ("rust-driver/src/main.rs", "rust"),
                   ("rust-driver/Cargo.toml", "rust"))
        for name, selected in targets:
            for only in (None, selected):
                with self.subTest(input=name, only=only):
                    self.build()
                    path = self.output.resolve() / name
                    contents = path.read_bytes()
                    external = self.root / ("external-package-" + name.replace("/", "-"))
                    external.write_bytes(contents)
                    path.unlink()
                    os.link(external, path)
                    before = external.stat()
                    calls = (self.output / "tool-calls.jsonl").read_bytes()
                    try:
                        with mock.patch.object(build, "acquire", wraps=build.acquire) as acquire:
                            attempt = self.attempt(only=only)
                        states = {str(p): {"contents_hex": p.read_bytes().hex(), "device": p.stat().st_dev,
                                  "inode": p.stat().st_ino, "links": p.stat().st_nlink} for p in (external, path)}
                        self.record(input=name, only=only, attempt=attempt, acquire_calls=acquire.call_count,
                                    compiler_calls_unchanged=(self.output / "tool-calls.jsonl").read_bytes() == calls,
                                    before={"contents_hex": contents.hex(), "device": before.st_dev,
                                            "inode": before.st_ino, "links": before.st_nlink}, after=states)
                        self.assertFalse(attempt["accepted"], attempt)
                        self.assertIn("generated package file must not have multiple hard links", attempt["error"])
                        self.assertEqual(acquire.call_count, 0)
                        self.assertEqual((self.output / "tool-calls.jsonl").read_bytes(), calls)
                        for p in (external, path):
                            self.assertEqual(p.read_bytes(), contents)
                            self.assertEqual((p.stat().st_dev, p.stat().st_ino, p.stat().st_nlink),
                                             (before.st_dev, before.st_ino, 2))
                        self.assertEqual(attempt["metadata"], {"drivers.json": False, "buildinputs.json": False,
                                                               "build-failure.json": True})
                        self.assertEqual(attempt["runner"]["resource_calls"], 0)
                        self.assertEqual(attempt["runner"]["driver_calls"], 0)
                    finally:
                        path.unlink()
                        path.write_bytes(contents)

    def test_non_jvm_partial_build_reuses_recorded_classpath_and_preserves_unselected_artifacts(self):
        self.build()
        empty = (self.root / "owned-empty-classpath").resolve()
        empty.mkdir()
        for only in ("go", "rust", "js"):
            with self.subTest(only=only):
                previous = json.loads((self.output / "buildinputs.json").read_text())
                classpath = previous["jvm_classpath_inputs"]["classpath"]
                definitions = {language: previous["drivers"][language] for language in ("java", "kotlin", "scala")}
                selected_files = {"go": lambda path: path == self.output.resolve() / "go-driver/driver",
                                  "rust": lambda path: path.is_relative_to(self.output.resolve() / "rust-driver"),
                                  "js": lambda path: path == self.output.resolve() / "js-runtime-inputs.json" or
                                                     path.is_relative_to(self.output.resolve() / "sources/js")}
                unselected = [row for row in previous["artifacts"] if not selected_files[only](Path(row["path"]))]
                text = self.output / "jvm/classpath.txt"
                edited = classpath + os.pathsep + str(empty)
                text.write_text(edited)
                calls = len((self.output / "tool-calls.jsonl").read_text().splitlines())
                self.build(only=only)
                current = json.loads((self.output / "buildinputs.json").read_text())
                new_calls = [json.loads(line) for line in
                             (self.output / "tool-calls.jsonl").read_text().splitlines()[calls:]]
                probe = self.probe_run()
                self.record(only=only, edited_text=edited, previous_classpath_inputs=previous["jvm_classpath_inputs"],
                            current_classpath_inputs=current["jvm_classpath_inputs"], previous_definitions=definitions,
                            current_definitions={language: current["drivers"][language] for language in definitions},
                            unselected_artifacts=unselected, current_artifacts=current["artifacts"],
                            new_calls=new_calls, runner=probe)
                self.assertEqual(current["jvm_classpath_inputs"], previous["jvm_classpath_inputs"])
                self.assertEqual({language: current["drivers"][language] for language in definitions}, definitions)
                self.assertEqual(text.read_text(), edited)
                self.assertNotIn(str(empty), current["jvm_classpath_inputs"]["classpath"].split(os.pathsep))
                self.assertFalse(any(Path(row["path"]).is_relative_to(empty) for row in current["artifacts"]))
                self.assertEqual(list(empty.iterdir()), [])
                self.assertTrue(all(row in current["artifacts"] for row in unselected))
                for row in unselected:
                    self.assertEqual(build.digest(Path(row["path"])), row["sha256"])
                    self.assertEqual(Path(row["path"]).stat().st_size, row["bytes"])
                self.assertFalse(any(row["tool"] == "gradle" for row in new_calls))
                self.assertEqual(probe["resource_calls"], 1)
                self.assertEqual(probe["driver_calls"], 0)

    def test_selected_jvm_build_adopts_fresh_regular_generated_classpath(self):
        self.build()
        for only in (None, "jvm"):
            with self.subTest(only=only):
                previous = json.loads((self.output / "buildinputs.json").read_text())
                artifact = Path(previous["jvm_classpath_inputs"]["classpath"].split(os.pathsep)[-1])
                generated = os.pathsep.join([str(self.output.resolve() / "jvm/classes/main"), str(artifact)])
                original_run = build.subprocess.run

                def run_and_write_classpath(*args, **kwargs):
                    result = original_run(*args, **kwargs)
                    if Path(str(args[0][0])).resolve() == (self.bin / "gradle").resolve() and result.returncode == 0:
                        (self.output / "jvm/classpath.txt").write_text(generated)
                    return result

                with mock.patch.object(build.subprocess, "run", side_effect=run_and_write_classpath):
                    self.build(only=only)
                current = json.loads((self.output / "buildinputs.json").read_text())
                self.record(only=only, previous_classpath=previous["jvm_classpath_inputs"]["classpath"],
                            generated_classpath=generated, current_classpath_inputs=current["jvm_classpath_inputs"],
                            definitions={language: current["drivers"][language] for language in ("java", "kotlin", "scala")})
                self.assertEqual((self.output / "jvm/classpath.txt").read_text(), generated)
                self.assertEqual(current["jvm_classpath_inputs"], build.jvm_classpath_inputs(generated))
                for language in ("java", "kotlin", "scala"):
                    self.assertEqual(current["drivers"][language]["argv"][1:3], ["-cp", generated])
                self.assertEqual(self.probe_run()["resource_calls"], 1)


if __name__ == "__main__":
    unittest.main()
