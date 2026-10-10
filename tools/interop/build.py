#!/usr/bin/env python3
"""指定ソースを取得し、変更しない本体と薄い公開ドライバーだけをビルドする。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / "snapshots.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_fingerprints():
    return {str(path.relative_to(HERE)): digest(path) for path in sorted(HERE.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
            and not any(part.startswith(".") for part in path.relative_to(HERE).parts)}


def source_inventory(root, language):
    # この入口の pnpm/tsc が作る場所だけを除く。他言語の出力はソース外に置く。
    generated = {"node_modules", "packages/library/node_modules", "packages/examples/node_modules",
                 "packages/tests/node_modules", "packages/library/dist"} if language == "js" else set()
    inventory = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in list(directories):
            path = Path(directory) / name
            if str(path.relative_to(root)) in generated:
                directories.remove(name)
        for name in directories + files:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                inventory[relative] = {"symlink": os.readlink(path)}
            elif stat.S_ISREG(mode):
                inventory[relative] = {"sha256": digest(path)}
            elif not stat.S_ISDIR(mode):
                raise RuntimeError(f"unsupported source file: {path}")
    return inventory


def inventory_digest(inventory):
    return hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()


def verify_sources(records):
    for record in records:
        path = Path(record["path"])
        if str(path.resolve()) != record["resolved_path"] or not path.is_symlink():
            raise RuntimeError(f"source alias mismatch: {path}")
        if digest(Path(record["archive_path"])) != record["archive_sha256"]:
            raise RuntimeError(f"source archive changed: {path}")
        if inventory_digest(source_inventory(path, record["language"])) != record["file_inventory_sha256"]:
            raise RuntimeError(f"source inventory mismatch: {path}")


def jvm_classpath_inputs(classpath):
    directories = []
    for entry in classpath.split(os.pathsep):
        if not entry:
            raise RuntimeError("empty JVM classpath entry")
        path = Path(entry)
        if path.is_file():
            continue
        record = {"path": str(path), "resolved_path": str(path.resolve()), "exists": path.exists(),
                  "symlink": os.readlink(path) if path.is_symlink() else None, "files": {}}
        if record["exists"]:
            if not path.is_dir():
                raise RuntimeError(f"unsupported JVM classpath entry: {path}")
            for directory, children, files in os.walk(path, followlinks=False):
                for name in children + files:
                    file = Path(directory) / name
                    mode = file.lstat().st_mode
                    if stat.S_ISREG(mode):
                        record["files"][str(file.relative_to(path))] = {"sha256": digest(file), "bytes": file.stat().st_size}
                    elif not stat.S_ISDIR(mode):
                        raise RuntimeError(f"unsupported JVM classpath file: {file}")
        directories.append(record)
    return {"classpath": classpath, "directories": directories}


def verify_artifacts(inputs):
    for artifact in inputs["artifacts"]:
        path = Path(artifact["path"])
        if path.stat().st_size != artifact["bytes"] or digest(path) != artifact["sha256"]:
            raise RuntimeError(f"build artifact mismatch: {path}")
    jvm = inputs.get("jvm_classpath_inputs")
    if not jvm:
        raise RuntimeError("JVM classpath inputs missing; rebuild all drivers")
    for language in ("java", "kotlin", "scala"):
        if inputs["drivers"][language]["argv"][1:3] != ["-cp", jvm["classpath"]]:
            raise RuntimeError(f"JVM classpath definition mismatch: {language}")
    if jvm_classpath_inputs(jvm["classpath"]) != jvm:
        raise RuntimeError("JVM classpath directory inputs mismatch; rebuild all drivers")
    manifest = inputs.get("js_runtime_inputs")
    if not manifest:
        raise RuntimeError("JavaScript runtime inputs missing; rebuild all drivers")
    result = subprocess.run(["node", str(HERE / "drivers/js/runtime-inputs.cjs"), "--verify", manifest],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"JavaScript runtime inputs mismatch: {result.stderr.strip()}")


def source_recovery(output, **record):
    with (output / "source-recovery.jsonl").open("a") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def acquire(output):
    sources = output / "sources"
    sources.mkdir(exist_ok=True)
    records = []
    for language, sha in PINS["sources"].items():
        archive = sources / f"{language}.tar.gz"
        destination = sources / f"event-store-adapter-{language}-{sha}"
        url = f"https://codeload.github.com/j5ik2o/event-store-adapter-{language}/tar.gz/{sha}"

        def archive_inventory(path):
            try:
                with tarfile.open(path) as package:
                    members = package.getmembers()
                    if not members or any(member.name.split("/")[0] != destination.name for member in members):
                        return None
                    expected = {}
                    for member in members:
                        name = str(Path(member.name).relative_to(destination.name))
                        if member.isfile():
                            expected[name] = {"sha256": hashlib.sha256(package.extractfile(member).read()).hexdigest()}
                        elif member.issym():
                            expected[name] = {"symlink": member.linkname}
                    return expected
            except (tarfile.TarError, EOFError):
                return None

        expected = archive_inventory(archive) if archive.exists() else None
        if expected is None:
            if archive.exists():
                source_recovery(output, language=language, path=str(archive), kind="archive", phase="incomplete",
                                error="cached source archive is unreadable or does not match the pin")
            with tempfile.TemporaryDirectory(prefix=f".{language}-download-", dir=sources) as temporary:
                candidate = Path(temporary) / archive.name
                with urllib.request.urlopen(url, timeout=60) as response:
                    candidate.write_bytes(response.read())
                expected = archive_inventory(candidate)
                if expected is None:
                    raise RuntimeError(f"source archive does not match pin: {language}: {sha}")
                candidate.replace(archive)
            source_recovery(output, language=language, path=str(archive), kind="archive", phase="acquired")
        if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
            raise RuntimeError(f"source destination is not a directory: {destination}")
        # ビルドが読むソースを取得したアーカイブと照合する。成果物の版文字列に頼らない。
        actual = source_inventory(destination, language)
        mismatches = sorted(name for name in actual if expected.get(name) != actual[name])
        if mismatches:
            raise RuntimeError(f"source archive mismatch: {language}: {mismatches}")
        missing = sorted(expected.keys() - actual.keys())
        if not destination.exists() or missing:
            if destination.exists():
                source_recovery(output, language=language, path=str(destination), kind="directory", phase="incomplete",
                                error="cached source files missing", missing=missing, file_inventory_sha256=inventory_digest(actual))
            with tempfile.TemporaryDirectory(prefix=f".{language}-extract-", dir=sources) as temporary:
                temporary = Path(temporary)
                with tarfile.open(archive) as package:
                    package.extractall(temporary, filter="data")
                candidate = temporary / destination.name
                if candidate.is_symlink() or not candidate.is_dir():
                    raise RuntimeError(f"source destination is not a directory: {candidate}")
                actual = source_inventory(candidate, language)
                if actual != expected:
                    raise RuntimeError(f"source archive mismatch after extraction: {language}")
                backup = temporary / "incomplete-cache"
                if destination.exists():
                    destination.rename(backup)
                try:
                    candidate.rename(destination)
                except Exception:
                    if backup.exists():
                        backup.rename(destination)
                    raise
            source_recovery(output, language=language, path=str(destination), kind="directory", phase="acquired", missing=missing)
        alias = sources / language
        if alias.is_symlink():
            alias.unlink()
        elif alias.exists():
            raise RuntimeError(f"source alias is not a symlink: {alias}")
        alias.symlink_to(destination)
        records.append({"language": language, "source_sha": sha, "archive_sha256": digest(archive),
                        "archive_path": str(archive), "url": url, "path": str(alias),
                        "resolved_path": str(destination.resolve()), "archive_matches_source": True,
                        "file_count": len(actual), "file_inventory_sha256": inventory_digest(actual)})
    save(output / "source-inputs.json", records)
    return sources


def java_artifacts(output, supplied):
    snapshot = PINS["java_currentSnapshot"]
    artifacts = []
    for suffix, key in [(".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")]:
        path = output / (snapshot["artifact"] + suffix)
        if not path.exists():
            source = Path(supplied) / path.name if supplied else None
            if source and source.exists():
                shutil.copyfile(source, path)
            else:
                with urllib.request.urlopen(snapshot["repository"] + path.name, timeout=60) as response:
                    path.write_bytes(response.read())
        if digest(path) != snapshot[key]:
            raise RuntimeError(f"Java currentSnapshot digest mismatch: {path}")
        artifacts.append(path)
    with zipfile.ZipFile(artifacts[1]) as package:
        names = [n for n in package.namelist() if n.endswith(".java")]
        source_root = output / "sources/java/src/main/java"
        source_files = {str(p.relative_to(source_root)) for p in source_root.rglob("*.java")}
        if set(names) != source_files or any(package.read(n) != (source_root / n).read_bytes() for n in names):
            raise RuntimeError("Java published sources do not match the pinned source")
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gradle", default="gradle")
    parser.add_argument("--java-artifact-directory", type=Path)
    parser.add_argument("--only", choices=("jvm", "go", "rust", "js"), help="変更したドライバーだけを再ビルドする")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commands = json.loads((output / "build-commands.json").read_text()) if (output / "build-commands.json").exists() else []
    previous_inputs = json.loads((output / "buildinputs.json").read_text()) if (output / "buildinputs.json").exists() else None
    previous_success = (output / "drivers.json").exists() and not (output / "build-failure.json").exists()
    # 取得失敗や途中の成果物更新でも、前回の成功を今回の結果として使わせない。
    for name in ("drivers.json", "buildinputs.json"):
        (output / name).unlink(missing_ok=True)
    selected = lambda language: args.only is None or args.only == language

    def execute(label, command, cwd=None, environment=None):
        attempt = 1 + sum(row["label"] == label for row in commands)
        log = output / f"build-{label}-{attempt}.log"
        row = {"label": label, "argv": [str(v) for v in command], "cwd": str(cwd or HERE), "log": str(log)}
        commands.append(row)
        save(output / "build-commands.json", commands)
        started = time.monotonic()
        with log.open("w") as stream:
            result = subprocess.run(row["argv"], cwd=cwd or HERE, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        row.update(exit=result.returncode, elapsed_seconds=round(time.monotonic() - started, 3))
        save(output / "build-commands.json", commands)
        print(label, "exit", result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(f"{label} failed: {log}")

    try:
        if not __debug__:
            raise RuntimeError("build requires assertions; run without -O or PYTHONOPTIMIZE")
        if args.only:
            if not previous_success or previous_inputs is None or previous_inputs["currentSnapshot"] != PINS:
                raise RuntimeError("--only requires a successful build with the current pins; rebuild all drivers")
            if not previous_inputs.get("js_runtime_inputs"):
                raise RuntimeError("--only requires current runtime input coverage; rebuild all drivers")
            verify_sources(previous_inputs["sources"])
            verify_artifacts(previous_inputs)
            unchanged = lambda path: path.startswith("drivers/") and not path.startswith(f"drivers/{args.only}/")
            expected = {path: sha for path, sha in previous_inputs["driver_sources"].items() if unchanged(path)}
            actual = {path: sha for path, sha in source_fingerprints().items() if unchanged(path)}
            if actual != expected:
                raise RuntimeError("unselected driver sources changed; rebuild all drivers")
        sources = acquire(output)
        artifacts = java_artifacts(output, args.java_artifact_directory)
        jvm = output / "jvm"
        if selected("jvm"):
            execute("jvm", [args.gradle, "--no-daemon", "--console", "plain", "--project-cache-dir", output / "gradle-cache",
                         "-p", HERE / "drivers/jvm", f"-PlibrarySources={sources}", f"-PoutputDir={jvm}",
                         f"-PjavaArtifact={artifacts[0]}", "writeClasspath"])
        go = output / "go-driver"
        go.mkdir(exist_ok=True)
        if selected("go"):
            shutil.copyfile(HERE / "drivers/go/main.go", go / "main.go")
            # 本体と同じ依存集合。置換先の実ソースを使うので公開版番号は仮定しない。
            original = (sources / "go/go.mod").read_text()
            module = "github.com/j5ik2o/event-store-adapter-go/v2"
            (go / "go.mod").write_text(original.replace(f"module {module}", "module interop-driver", 1)
                + f"\nrequire {module} v2.0.0-00010101000000-000000000000\nreplace {module} => {sources / 'go'}\n")
            shutil.copyfile(sources / "go/go.sum", go / "go.sum")
            execute("go", ["go", "build", "-mod=mod", "-o", go / "driver", "."], cwd=go)
        rust = output / "rust-driver"
        (rust / "src").mkdir(parents=True, exist_ok=True)
        if selected("rust"):
            shutil.copyfile(HERE / "drivers/rust/main.rs", rust / "src/main.rs")
            (rust / "Cargo.toml").write_text(f'''[package]
name = "interop-driver"
version = "0.0.0"
edition = "2021"
[dependencies]
event-store-adapter-rs = {{ path = "{sources / 'rs/lib'}", features = ["dynamodb"] }}
aws-sdk-dynamodb = "1.23.0"
aws-smithy-async = {{ version = "1.3.0", features = ["rt-tokio"] }}
chrono = "0.4.38"
serde_json = "1.0"
tokio = {{ version = "1.37.0", features = ["full"] }}
''')
        if selected("rust"):
            execute("rust", ["cargo", "build", "--manifest-path", rust / "Cargo.toml"])
            execute("rust-inputs", ["cargo", "metadata", "--format-version", "1", "--manifest-path", rust / "Cargo.toml"])
        if selected("js"):
            execute("js-install", ["pnpm", "install", "--frozen-lockfile"], cwd=sources / "js")
            execute("js", ["pnpm", "--filter", "event-store-adapter-js", "build"], cwd=sources / "js")
            execute("js-inputs", ["node", HERE / "drivers/js/runtime-inputs.cjs", "--record",
                                  sources / "js/packages/library", output / "js-runtime-inputs.json"])
        if selected("go"):
            execute("go-inputs", ["go", "list", "-m", "-json", "all"], cwd=go)
        classpath = (jvm / "classpath.txt").read_text()
        drivers = {language: {"argv": ["java", "-cp", classpath, main], "env": {}}
                   for language, main in [("java", "interop.JavaDriver"), ("kotlin", "interop.KotlinDriverKt"), ("scala", "interop.ScalaDriver")]}
        drivers["go"] = {"argv": [str(go / "driver")], "env": {}}
        drivers["rs"] = {"argv": [str(rust / "target/debug/interop-driver")], "env": {}}
        drivers["js"] = {"argv": ["node", str(HERE / "drivers/js/driver.mjs")],
                         "env": {"INTEROP_JS_LIBRARY": str(sources / "js/packages/library"),
                                 "INTEROP_JS_INPUTS": str(output / "js-runtime-inputs.json")}}
        inputs = {"currentSnapshot": PINS, "sources": json.loads((output / "source-inputs.json").read_text()),
                  "java_sources_match_pinned_source": True, "artifacts": [], "driver_sources": {},
                  "js_runtime_inputs": str(output / "js-runtime-inputs.json"),
                  "jvm_classpath_inputs": jvm_classpath_inputs(classpath), "drivers": drivers}
        files = artifacts + [go / "driver", go / "go.mod", go / "go.sum", rust / "Cargo.lock", rust / "target/debug/interop-driver"]
        files += [Path(inputs["js_runtime_inputs"])]
        files += [Path(row["path"]) for row in json.loads(Path(inputs["js_runtime_inputs"]).read_text())["files"]]
        files += [Path(p) for p in classpath.split(os.pathsep) if Path(p).is_file()]
        files += [Path(directory["path"]) / name for directory in inputs["jvm_classpath_inputs"]["directories"]
                  for name in directory["files"]]
        for path in sorted(set(files)):
            inputs["artifacts"].append({"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size})
        inputs["driver_sources"] = source_fingerprints()
        verify_sources(inputs["sources"])
        verify_artifacts(inputs)
        save(output / "buildinputs.json", inputs)
        save(output / "drivers.json", drivers)
        (output / "build-failure.json").unlink(missing_ok=True)
    except Exception as error:
        for name in ("drivers.json", "buildinputs.json"):
            (output / name).unlink(missing_ok=True)
        save(output / "build-failure.json", {"error": str(error), "commands": commands})
        raise


if __name__ == "__main__":
    main()
