#!/usr/bin/env python3
"""指定ソースを取得し、変更しない本体と薄い公開ドライバーだけをビルドする。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / "snapshots.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def external_output(path):
    output = path.resolve()
    if output.is_relative_to(HERE.resolve()):
        raise RuntimeError(f"output must be outside tools/interop: {output}")
    return output


def download(url, path):
    with urllib.request.urlopen(url, timeout=120) as response:
        path.write_bytes(response.read())


def acquire(output):
    root = output / "sources"
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for language, sha in PINS["sources"].items():
        expected = PINS["source_archives"][language]["sha256"]
        url = f"https://codeload.github.com/j5ik2o/event-store-adapter-{language}/tar.gz/{sha}"
        archive = root / f"{language}.tar.gz"
        if not archive.exists() or digest(archive) != expected:
            download(url, archive)
        if digest(archive) != expected:
            raise RuntimeError(f"source archive digest mismatch: {language}")
        directory = root / f"event-store-adapter-{language}-{sha}"
        if not directory.exists():
            with tarfile.open(archive) as package:
                package.extractall(root, filter="data")
        link = root / language
        link.unlink(missing_ok=True)
        link.symlink_to(directory.name)
        records.append({"language": language, "source_sha": sha, "archive_sha256": expected,
                        "url": url, "path": str(directory)})
    return root, records


def java_artifacts(output, supplied):
    snapshot = PINS["java_artifact"]
    source_root = output / "sources/java/src/main/java"
    source_files = {str(p.relative_to(source_root)) for p in source_root.rglob("*.java")}
    artifacts = []
    for suffix, key in [(".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")]:
        path = output / (snapshot["artifact"] + suffix)
        if not path.exists() or digest(path) != snapshot[key]:
            if supplied:
                shutil.copyfile(Path(supplied) / path.name, path)
            else:
                download(snapshot["repository"] + path.name, path)
        if digest(path) != snapshot[key]:
            raise RuntimeError(f"Java artifact digest mismatch: {path}")
        artifacts.append(path)
    # 公開 sources jar が固定した java のコミットと同じ内容であることが、jar とコミットの対応の根拠になる。
    with zipfile.ZipFile(artifacts[1]) as package:
        names = [n for n in package.namelist() if n.endswith(".java")]
        if set(names) != source_files or any(package.read(n) != (source_root / n).read_bytes() for n in names):
            raise RuntimeError("Java published sources do not match the pinned source")
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gradle", default="gradle")
    parser.add_argument("--java-artifact-directory", type=Path)
    args = parser.parse_args()
    output = external_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    commands = []

    def execute(label, argv, cwd=None, environment=None):
        log = output / f"build-{label}.log"
        row = {"label": label, "argv": [str(v) for v in argv], "cwd": str(cwd or HERE), "log": str(log)}
        commands.append(row)
        started = time.monotonic()
        with log.open("wb") as stream:
            result = subprocess.run(row["argv"], cwd=cwd or HERE, env={**os.environ, **(environment or {})},
                                    stdout=stream, stderr=subprocess.STDOUT)
        row.update(exit=result.returncode, elapsed_seconds=round(time.monotonic() - started, 3))
        save(output / "build-commands.json", commands)
        print(label, "exit", result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(f"{label} failed: {log}")

    try:
        (output / "drivers.json").unlink(missing_ok=True)
        sources, records = acquire(output)
        jar = java_artifacts(output, args.java_artifact_directory)[0]
        jvm, go, rust = output / "jvm", output / "go-driver", output / "rust-driver"

        for name in ("classes", "resources"):
            shutil.rmtree(jvm / name, ignore_errors=True)
        execute("jvm", [args.gradle, "--no-daemon", "--console", "plain", "--project-cache-dir", output / "gradle-cache",
                        "-p", HERE / "drivers/jvm", f"-PlibrarySources={sources}", f"-PoutputDir={jvm}",
                        f"-PjavaArtifact={jar}", "writeClasspath"])

        go.mkdir(exist_ok=True)
        shutil.copyfile(HERE / "drivers/go/main.go", go / "main.go")
        # 置換先の実ソースを使うので、公開版番号は仮定しない。
        module = "github.com/j5ik2o/event-store-adapter-go/v5"
        original = (sources / "go/go.mod").read_text()
        (go / "go.mod").write_text(original.replace(f"module {module}", "module interop-driver", 1)
            + f"\nrequire {module} v5.0.0-00010101000000-000000000000\nreplace {module} => {json.dumps(str(sources / 'go'), ensure_ascii=False)}\n")
        shutil.copyfile(sources / "go/go.sum", go / "go.sum")
        execute("go", ["go", "build", "-mod=mod", "-o", go / "driver", "."], cwd=go, environment={"GOWORK": "off"})

        (rust / "src").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / "drivers/rust/main.rs", rust / "src/main.rs")
        (rust / "Cargo.toml").write_text(f'''[package]
name = "interop-driver"
version = "0.0.0"
edition = "2021"
[dependencies]
event-store-adapter-rs = {{ path = {json.dumps(str(sources / 'rs/lib'), ensure_ascii=False)}, features = ["dynamodb"] }}
aws-sdk-dynamodb = "1.23.0"
aws-smithy-async = {{ version = "1.3.0", features = ["rt-tokio"] }}
chrono = "0.4.38"
serde_json = "1.0"
tokio = {{ version = "1.37.0", features = ["full"] }}
''')
        execute("rust", ["cargo", "build", "--manifest-path", rust / "Cargo.toml", "--target-dir", rust / "target"])

        execute("js-install", ["pnpm", "install", "--frozen-lockfile"], cwd=sources / "js")
        execute("js", ["pnpm", "--filter", "event-store-adapter-js", "build"], cwd=sources / "js")

        classpath = (jvm / "classpath.txt").read_text()
        drivers = {language: {"argv": ["java", "-cp", classpath, main], "env": {}}
                   for language, main in [("java", "interop.JavaDriver"), ("kotlin", "interop.KotlinDriverKt"),
                                          ("scala", "interop.ScalaDriver")]}
        drivers["go"] = {"argv": [str(go / "driver")], "env": {}}
        drivers["rs"] = {"argv": [str(rust / "target/debug/interop-driver")], "env": {}}
        drivers["js"] = {"argv": ["node", str(HERE / "drivers/js/driver.mjs")],
                         "env": {"INTEROP_JS_LIBRARY": str(sources / "js/packages/library")}}
        save(output / "buildinputs.json", {"currentSnapshot": PINS, "sources": records})
        save(output / "drivers.json", drivers)
        (output / "build-failure.json").unlink(missing_ok=True)
    except Exception as error:
        save(output / "build-failure.json", {"error": str(error), "commands": commands})
        raise


if __name__ == "__main__":
    main()
