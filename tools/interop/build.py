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
JS_DEPENDENCY_DIRECTORIES = ("node_modules", "packages/library/node_modules", "packages/examples/node_modules",
                             "packages/tests/node_modules")


def child_environment(extra=None):
    environment = dict(os.environ)
    environment.update(extra or {})
    # ドライバーやビルドの検査より先にコードを読む設定だけを、子から除く。
    for name in ("NODE_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS",
                 "JAVA_OPTS", "GRADLE_OPTS", "LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES"):
        environment.pop(name, None)
    return environment


def pnpm_hook_environment():
    # 同じ設定の大小文字・区切り違いも子だけで固定し、入れ子のpnpmへ引き継ぐ。
    environment = {name: "true" for name in os.environ if name.lower().startswith("pnpm_config_") and
                   name[len("pnpm_config_"):].lower().replace("_", "").replace("-", "") == "ignorepnpmfile"}
    environment["PNPM_CONFIG_IGNORE_PNPMFILE"] = "true"
    return environment


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    # 失敗記録の保存先がlinkでも参照先へ書かず、同じ親で置換する。
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def verify_metadata_output(output):
    for name in ("build-commands.json", "buildinputs.json", "drivers.json", "build-failure.json",
                 "source-inputs.json", "js-runtime-inputs.json", "source-recovery.jsonl"):
        path = output / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RuntimeError(f"build metadata must be a regular file: {path}")
    verify_source_recovery_output(output)


def verify_source_recovery_output(output):
    path = output / "source-recovery.jsonl"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"build metadata must be a regular file: {path}")
    if path.exists() and path.stat().st_nlink > 1:
        raise RuntimeError(f"source recovery log must not have multiple hard links: {path}")


def source_fingerprints():
    verify_driver_sources()
    fingerprints = {}
    for path in sorted(HERE.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(HERE)
        # GradleのJavaは直下、Kotlin・Scalaは再帰で、隠しファイルもコンパイルする。
        jvm_source = relative.parts[:2] == ("drivers", "jvm") and (
            relative.name.endswith((".kt", ".scala")) or
            len(relative.parts) == 3 and relative.name.endswith(".java"))
        if jvm_source or ("__pycache__" not in relative.parts and not any(part.startswith(".") for part in relative.parts)):
            fingerprints[str(relative)] = digest(path)
    return fingerprints


def verify_jvm_sources():
    root = HERE / "drivers/jvm"
    for path in (root.parent, root):
        if path.is_symlink():
            raise RuntimeError(f"JVM source directory must be a real directory: {path}")
    # 欠落linkはfiles側に入る。取得後にdirectoryになる可能性もあるため先に拒否する。
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            if path.is_symlink() and not path.exists():
                raise RuntimeError(f"JVM source link target is missing: {path}")
            if path.is_symlink() and path.is_dir():
                raise RuntimeError(f"JVM source directory must be a real directory: {path}")


def verify_driver_sources():
    verify_jvm_sources()
    # rglobが降りないdirectory linkを、全driverで取得・起動より前に拒否する。
    for directory, directories, files in os.walk(HERE / "drivers", followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            if path.is_symlink() and not path.exists():
                raise RuntimeError(f"driver source link target is missing: {path}")
            if path.is_symlink() and path.is_dir():
                raise RuntimeError(f"driver source directory must be a real directory: {path}")


def external_output(path):
    output = path.resolve()
    if output.is_relative_to(HERE.resolve()):
        raise RuntimeError(f"output must be outside tools/interop: {output}")
    if os.pathsep in str(output):
        raise RuntimeError(f"output must not contain the Java classpath separator {os.pathsep!r}: {output}")
    return output


def verify_generated_package(root, files, directories=()):
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise RuntimeError(f"generated package directory must be a real directory: {root}")
    if root.exists():
        for path in sorted(root.iterdir()):
            if not path.is_symlink() and ((path.name in files and path.is_file())
                                         or (path.name in directories and path.is_dir())):
                if path.name in files and path.is_file() and path.stat().st_nlink > 1:
                    raise RuntimeError(f"generated package file must not have multiple hard links: {path}")
                continue
            raise RuntimeError(f"unexpected generated package input: {path}")


def verify_jvm_output(output):
    root = output / "jvm"
    generated = [root / name for name in ("classes", "resources", "tmp", "kotlin", "generated", "reports")]
    # 両子を消す前に親も確認する。親のリンク経由では子のis_symlinkだけでは足りない。
    for path in (root, *generated, output / "gradle-cache"):
        if path.is_symlink() or (path.exists() and not path.is_dir()) or not path.resolve().is_relative_to(output):
            raise RuntimeError(f"JVM output directory must be a real directory inside output: {path}")
    # 固定Gradleの既知生成先では、作業状態のfile linkも外部への書込みになる。
    for tree in generated:
        for directory, directories, files in os.walk(tree, followlinks=False):
            for name in directories + files:
                path = Path(directory) / name
                mode = path.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise RuntimeError(f"JVM output entry must be a regular file or directory: {path}")
    for name in ("classpath.txt", "dependencies.txt"):
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_file()) or not path.resolve().is_relative_to(output):
            raise RuntimeError(f"JVM output file must be a regular file inside output: {path}")
        if path.exists() and path.stat().st_nlink > 1:
            raise RuntimeError(f"JVM output file must not have multiple hard links: {path}")


def verify_sources_root(output):
    root = output / "sources"
    if root.is_symlink() or (root.exists() and not root.is_dir()) or not root.resolve().is_relative_to(output.resolve()):
        raise RuntimeError(f"source cache directory must be a real directory inside output: {root}")


def gradle_init_inputs(command):
    environment = child_environment()
    executable = shutil.which(str(command), path=environment.get("PATH"))
    if executable is None:
        raise RuntimeError(f"Gradle launcher not found: {command}")
    launcher = Path(executable).resolve()
    installation = launcher.parent.parent
    # ラッパーから先の配布物は起動前に確定できない。既存の配布物のbin/gradleを使う。
    if launcher.parent.name != "bin" or launcher.name not in ("gradle", "gradle.bat") or not list((installation / "lib").glob("gradle-launcher-*.jar")):
        raise RuntimeError(f"Gradle requires a distribution bin/gradle launcher: {launcher}")
    home = Path(environment.get("GRADLE_USER_HOME") or Path.home() / ".gradle").expanduser()
    if not home.is_absolute():
        home = HERE / home
    home = home.resolve()
    files = [home / "init.gradle", home / "init.gradle.kts"]
    directories = [home / "init.d", installation / "init.d"]
    for directory in directories:
        if directory.exists() and not directory.is_dir():
            raise RuntimeError(f"unsupported Gradle initialization directory: {directory}")
        files += sorted(path for path in directory.glob("*") if path.name.endswith((".gradle", ".gradle.kts")))
    # 設定や認証情報の内容は読まず、実適用される初期化スクリプトの存在だけを検査する。
    for path in files:
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"unrecorded Gradle initialization script: {path}")
    properties = []
    for path in dict.fromkeys((home / "gradle.properties", HERE / "drivers/jvm/gradle.properties",
                               installation / "gradle.properties")):
        # 実適用先だけを調べる。空の通常fileは記録し、設定・秘密の内容は読まない。
        exists = path.exists()
        if path.is_symlink() or exists and (not path.is_file() or path.stat().st_size):
            raise RuntimeError(f"unrecorded Gradle properties: {path}")
        properties.append({"path": str(path), "exists": exists, "bytes": 0 if exists else None})
    return {"launcher": str(launcher), "gradle_home": str(installation), "gradle_user_home": str(home),
            "absent_init_files": [str(path) for path in files],
            "properties_files": properties,
            "init_directories": [{"path": str(path), "resolved_path": str(path.resolve()), "exists": path.exists()} for path in directories]}


def cargo_config_inputs(extra=None):
    environment = child_environment(extra)
    cwd = HERE.resolve()
    home = Path(environment.get("CARGO_HOME") or Path.home() / ".cargo").expanduser()
    if not home.is_absolute():
        home = cwd / home
    home = home.resolve()
    roots = [path / ".cargo" for path in (cwd, *cwd.parents)] + [home]
    paths = list(dict.fromkeys(root / name for root in roots for name in ("config", "config.toml")))
    # Cargoはmanifestの場所ではなく呼出し場所から探索する。秘密を含み得る内容は読まない。
    for path in paths:
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"unrecorded Cargo configuration: {path}")
    for name in ("RUSTC", "CARGO_BUILD_RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                 "CARGO_BUILD_RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_TARGET",
                 "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS"):
        if environment.get(name):
            raise RuntimeError(f"unrecorded Cargo compiler environment: {name}")
    for name, value in environment.items():
        if name.startswith("CARGO_TARGET_") and name.endswith(("_RUSTFLAGS", "_LINKER")) and value:
            raise RuntimeError(f"unrecorded Cargo compiler environment: {name}")
    return {"cwd": str(cwd), "cargo_home": str(home), "absent_config_files": [str(path) for path in paths]}


def verify_cargo_home(home, output):
    if home.is_symlink() or not home.is_dir() or home.parent != output or home.resolve() != home:
        raise RuntimeError(f"Cargo home must be a real directory inside output: {home}")


def verify_cargo_metadata(metadata, home, rust, sources):
    if Path(metadata["target_directory"]).resolve() != rust / "target":
        raise RuntimeError("Cargo target directory does not match the recorded binary")
    manifests = {package["name"]: Path(package["manifest_path"]).resolve()
                 for package in metadata["packages"] if package["source"] is None}
    if (manifests.get("interop-driver") != rust / "Cargo.toml" or
            manifests.get("event-store-adapter-rs") != (sources / "rs/lib/Cargo.toml").resolve()):
        raise RuntimeError("Cargo package sources do not match the generated driver and pinned library")
    registry_packages = 0
    for package in metadata["packages"]:
        if not (package["source"] or "").startswith("registry+"):
            continue
        manifest = Path(package["manifest_path"])
        if (manifest.is_symlink() or not manifest.is_file() or
                not manifest.resolve().is_relative_to(home / "registry/src")):
            raise RuntimeError("Cargo registry source must be inside the fresh Cargo home")
        registry_packages += 1
    return {"cargo_home": str(home), "registry_packages": registry_packages,
            "driver_manifest": str(manifests["interop-driver"]),
            "library_manifest": str(manifests["event-store-adapter-rs"])}


def source_inventory(root, language):
    # この入口の pnpm/tsc が作る場所だけを除く。他言語の出力はソース外に置く。
    generated = set(JS_DEPENDENCY_DIRECTORIES) | {"packages/library/dist"} if language == "js" else set()
    inventory = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            if str(path.relative_to(root)) in generated:
                if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(root.resolve()):
                    raise RuntimeError(f"generated source directory must be a real directory inside source cache: {path}")
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
        verify_sources_root(path.parent.parent)
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
                            capture_output=True, text=True, env=child_environment())
    if result.returncode:
        raise RuntimeError(f"JavaScript runtime inputs mismatch: {result.stderr.strip()}")


def source_recovery(output, **record):
    verify_source_recovery_output(output)
    with (output / "source-recovery.jsonl").open("a") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def acquire(output):
    verify_sources_root(output)
    archive_pins = PINS.get("source_archives", {})
    if set(archive_pins) != set(PINS["sources"]):
        raise RuntimeError("source archive pin mismatch: update source commits and archive digests together")
    for language, sha in PINS["sources"].items():
        pin = archive_pins[language]
        expected_digest = pin.get("sha256", "")
        if pin.get("source_sha") != sha or len(expected_digest) != 64 or any(c not in "0123456789abcdef" for c in expected_digest):
            raise RuntimeError(f"source archive pin mismatch: {language}: {sha}")
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

        expected_digest = archive_pins[language]["sha256"]
        expected = archive_inventory(archive) if archive.exists() and digest(archive) == expected_digest else None
        if expected is None:
            if archive.exists():
                source_recovery(output, language=language, path=str(archive), kind="archive", phase="incomplete",
                                error="cached source archive is unreadable or does not match the pin",
                                archive_sha256=digest(archive), expected_sha256=expected_digest)
            with tempfile.TemporaryDirectory(prefix=f".{language}-download-", dir=sources) as temporary:
                candidate = Path(temporary) / archive.name
                with urllib.request.urlopen(url, timeout=60) as response:
                    candidate.write_bytes(response.read())
                if digest(candidate) != expected_digest:
                    raise RuntimeError(f"source archive digest mismatch: {language}: {sha}")
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
                backup = None
                if destination.exists():
                    # 元の依存・生成物・リンクも含めて保持し、退避世代は自動削除しない。
                    backup = Path(tempfile.mkdtemp(prefix=f".source-cache-backup-{language}-", dir=output)) / destination.name
                    destination.rename(backup)
                try:
                    candidate.rename(destination)
                except Exception:
                    if backup is not None:
                        backup.rename(destination)
                    raise
            source_recovery(output, language=language, path=str(destination), kind="directory", phase="acquired", missing=missing,
                            **({"backup_path": str(backup)} if backup is not None else {}))
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
    source_root = output / "sources/java/src/main/java"
    source_files = {str(p.relative_to(source_root)) for p in source_root.rglob("*.java")}

    def validate(path, key):
        if digest(path) != snapshot[key]:
            raise RuntimeError(f"Java currentSnapshot digest mismatch: {path}")
        if key == "sources_sha256":
            with zipfile.ZipFile(path) as package:
                names = [n for n in package.namelist() if n.endswith(".java")]
                if set(names) != source_files or any(package.read(n) != (source_root / n).read_bytes() for n in names):
                    raise RuntimeError("Java published sources do not match the pinned source")

    artifacts = []
    with tempfile.TemporaryDirectory(prefix=".java-artifacts-", dir=output) as temporary:
        replacements = []
        for suffix, key in [(".jar", "jar_sha256"), ("-sources.jar", "sources_sha256")]:
            path = output / (snapshot["artifact"] + suffix)
            source = Path(supplied) / path.name if supplied else None
            # 明示された入力はキャッシュの有無にかかわらず検証し、不正なら代替取得しない。
            if source is not None:
                validate(source, key)
            if path.exists() and digest(path) == snapshot[key]:
                validate(path, key)
            else:
                path.unlink(missing_ok=True)
                candidate = Path(temporary) / path.name
                if source is not None:
                    shutil.copyfile(source, candidate)
                else:
                    with urllib.request.urlopen(snapshot["repository"] + path.name, timeout=60) as response:
                        candidate.write_bytes(response.read())
                validate(candidate, key)
                replacements.append((candidate, path))
            artifacts.append(path)
        # 2成果物の指紋と公開ソースの一致を確認してから、出力キャッシュへ確定する。
        for candidate, path in replacements:
            candidate.replace(path)
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gradle", default="gradle")
    parser.add_argument("--java-artifact-directory", type=Path)
    parser.add_argument("--only", choices=("jvm", "go", "rust", "js"), help="変更したドライバーだけを再ビルドする")
    args = parser.parse_args()
    output = external_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    commands = []
    previous_success = (output / "drivers.json").exists() and not (output / "build-failure.json").exists()
    selected = lambda language: args.only is None or args.only == language

    def execute(label, command, cwd=None, environment=None, capture_stdout=False):
        attempt = 1 + sum(row["label"] == label for row in commands)
        log = output / f"build-{label}-{attempt}.log"
        stdout = output / f"build-{label}-{attempt}.stdout"
        for path in [log] + ([stdout] if capture_stdout else []):
            if path.is_symlink() or (path.exists() and not path.is_file()) or not path.resolve().is_relative_to(output):
                raise RuntimeError(f"build diagnostic must be a regular file inside output: {path}")
            if path.exists() and path.stat().st_nlink > 1:
                raise RuntimeError(f"build diagnostic must not have multiple hard links: {path}")
        row = {"label": label, "argv": [str(v) for v in command], "cwd": str(cwd or HERE), "log": str(log)}
        commands.append(row)
        save(output / "build-commands.json", commands)
        started = time.monotonic()
        with log.open("wb") as stream:
            result = subprocess.run(row["argv"], cwd=cwd or HERE, env=child_environment(environment),
                                    stdout=subprocess.PIPE if capture_stdout else stream,
                                    stderr=stream if capture_stdout else subprocess.STDOUT)
            if capture_stdout:
                stdout.write_bytes(result.stdout)
                row["stdout"] = str(stdout)
                stream.write(result.stdout)
        row.update(exit=result.returncode, elapsed_seconds=round(time.monotonic() - started, 3))
        save(output / "build-commands.json", commands)
        print(label, "exit", result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(f"{label} failed: {log}")
        return row

    try:
        verify_metadata_output(output)
        # 成功を先に無効にし、部分ビルド用の前回入力も例外保護の中で読む。
        (output / "drivers.json").unlink(missing_ok=True)
        previous_text = (output / "buildinputs.json").read_text() if (output / "buildinputs.json").exists() else None
        (output / "buildinputs.json").unlink(missing_ok=True)
        commands = json.loads((output / "build-commands.json").read_text()) if (output / "build-commands.json").exists() else []
        previous_inputs = json.loads(previous_text) if previous_text is not None else None
        cargo_inputs = previous_inputs.get("cargo_config_inputs") if previous_inputs else None
        cargo_inherited_inputs = previous_inputs.get("cargo_inherited_config_inputs") if previous_inputs else None
        cargo_metadata_inputs = previous_inputs.get("cargo_metadata_inputs") if previous_inputs else None
        gradle_inputs = previous_inputs.get("gradle_init_inputs") if previous_inputs else None
        pnpm_inputs = previous_inputs.get("pnpm_hook_settings") if previous_inputs else None
        pnpm_virtual_store = previous_inputs.get("pnpm_virtual_store_dir") if previous_inputs else None
        if not __debug__:
            raise RuntimeError("build requires assertions; run without -O or PYTHONOPTIMIZE")
        verify_driver_sources()
        if selected("rust"):
            cargo_inherited_inputs = cargo_config_inputs()
        if args.only:
            if not previous_success or previous_inputs is None or previous_inputs["currentSnapshot"] != PINS:
                raise RuntimeError("--only requires a successful build with the current pins; rebuild all drivers")
            if previous_inputs["driver_sources"].get("build.py") != digest(HERE / "build.py"):
                raise RuntimeError("shared build input changed; rebuild all drivers")
            if not previous_inputs.get("js_runtime_inputs"):
                raise RuntimeError("--only requires current runtime input coverage; rebuild all drivers")
            verify_sources(previous_inputs["sources"])
            verify_artifacts(previous_inputs)
            unchanged = lambda path: path.startswith("drivers/") and not path.startswith(f"drivers/{args.only}/")
            expected = {path: sha for path, sha in previous_inputs["driver_sources"].items() if unchanged(path)}
            actual = {path: sha for path, sha in source_fingerprints().items() if unchanged(path)}
            if actual != expected:
                raise RuntimeError("unselected driver sources changed; rebuild all drivers")
        go = output / "go-driver"
        rust = output / "rust-driver"
        jvm = output / "jvm"
        go_environment = {"GOWORK": "off", "GOFLAGS": "", "GOENV": "off"}
        cargo_environment = {name: str(rust / "target") for name in
                             ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR", "CARGO_BUILD_BUILD_DIR")}
        if not selected("rust") and previous_inputs:
            cargo_environment = previous_inputs["cargo_build_environment"]
        # 生成パッケージの既知入力だけを上書きする。残留入力は消さず、取得・コンパイル前に拒否する。
        if selected("jvm"):
            verify_jvm_output(output)
            gradle_inputs = gradle_init_inputs(args.gradle)
        if selected("go"):
            verify_generated_package(go, {"main.go", "go.mod", "go.sum", "driver"})
        if selected("rust"):
            verify_generated_package(rust, {"Cargo.toml", "Cargo.lock"}, {"src", "target"})
            verify_generated_package(rust / "src", {"main.rs"})
            # 継承homeや前回の専用homeから依存を写さず、通常の取得で毎回展開する。
            cargo_home = Path(tempfile.mkdtemp(prefix=".cargo-home-", dir=output))
            verify_cargo_home(cargo_home, output)
            cargo_environment["CARGO_HOME"] = str(cargo_home)
            cargo_inputs = cargo_config_inputs(cargo_environment)
        verify_sources_root(output)
        sources = acquire(output)
        verify_driver_sources()
        artifacts = java_artifacts(output, args.java_artifact_directory)
        if selected("jvm"):
            # この入口が生成するクラスとリソースだけを再生成する。キャッシュは残す。
            verify_jvm_output(output)
            if gradle_init_inputs(args.gradle) != gradle_inputs:
                raise RuntimeError("Gradle initialization search changed before build")
            for path in (jvm / "classes", jvm / "resources"):
                if path.exists():
                    shutil.rmtree(path)
            verify_jvm_output(output)
            execute("jvm", [gradle_inputs["launcher"], "--no-daemon", "--console", "plain",
                         "--gradle-user-home", gradle_inputs["gradle_user_home"], "--project-cache-dir", output / "gradle-cache",
                         "-p", HERE / "drivers/jvm", f"-PlibrarySources={sources}", f"-PoutputDir={jvm}",
                         f"-PjavaArtifact={artifacts[0]}", "writeClasspath"])
        if selected("go"):
            go.mkdir(exist_ok=True)
            shutil.copyfile(HERE / "drivers/go/main.go", go / "main.go")
            # 本体と同じ依存集合。置換先の実ソースを使うので公開版番号は仮定しない。
            original = (sources / "go/go.mod").read_text()
            module = "github.com/j5ik2o/event-store-adapter-go/v2"
            (go / "go.mod").write_text(original.replace(f"module {module}", "module interop-driver", 1)
                + f"\nrequire {module} v2.0.0-00010101000000-000000000000\nreplace {module} => {json.dumps(str(sources / 'go'), ensure_ascii=False)}\n")
            shutil.copyfile(sources / "go/go.sum", go / "go.sum")
            execute("go-verify", ["go", "mod", "verify"], cwd=go, environment=go_environment)
            execute("go", ["go", "build", "-mod=mod", "-o", go / "driver", "."], cwd=go, environment=go_environment)
        if selected("rust"):
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
        if selected("rust"):
            verify_cargo_home(cargo_home, output)
            if (cargo_config_inputs() != cargo_inherited_inputs or
                    cargo_config_inputs(cargo_environment) != cargo_inputs):
                raise RuntimeError("Cargo configuration search changed before build")
            # 依存のfresh判定を以前のソースから引き継がない。元の全データは退避して残す。
            verify_generated_package(rust, {"Cargo.toml", "Cargo.lock"}, {"src", "target"})
            if (rust / "target").exists():
                backup = Path(tempfile.mkdtemp(prefix=".rust-target-backup-", dir=output))
                (rust / "target").rename(backup / "target")
            execute("rust", ["cargo", "build", "--manifest-path", rust / "Cargo.toml", "--target-dir", rust / "target"],
                    environment=cargo_environment)
            verify_cargo_home(cargo_home, output)
            if (cargo_config_inputs() != cargo_inherited_inputs or
                    cargo_config_inputs(cargo_environment) != cargo_inputs):
                raise RuntimeError("Cargo configuration search changed before metadata")
            metadata = execute("rust-inputs", ["cargo", "metadata", "--format-version", "1", "--manifest-path", rust / "Cargo.toml"],
                               environment=cargo_environment, capture_stdout=True)
            verify_cargo_home(cargo_home, output)
            if (cargo_config_inputs() != cargo_inherited_inputs or
                    cargo_config_inputs(cargo_environment) != cargo_inputs):
                raise RuntimeError("Cargo configuration search changed after metadata")
            cargo_metadata_inputs = verify_cargo_metadata(json.loads(Path(metadata["stdout"]).read_text()),
                                                         cargo_home, rust, sources)
        if selected("js"):
            pnpm_environment = pnpm_hook_environment()
            pnpm_inputs = {"ignore_pnpmfile": True, "arguments": ["--ignore-pnpmfile"], "environment": pnpm_environment}
            source_inventory(sources / "js", "js")
            # 温かいinstallが残す依存改変を採用しない。既知rootの全byteとaliasは退避して残す。
            roots = [name for name in JS_DEPENDENCY_DIRECTORIES if (sources / "js" / name).exists()]
            if roots:
                backup = Path(tempfile.mkdtemp(prefix=".js-dependencies-backup-", dir=output))
                for name in roots:
                    destination = backup / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    (sources / "js" / name).rename(destination)
            # 既知の生成・退避領域内に固定し、継承設定の外部依存配置先を使わない。
            pnpm_virtual_store = str((sources / "js/node_modules/.pnpm").resolve())
            execute("js-install", ["pnpm", "--ignore-pnpmfile", "install", "--frozen-lockfile",
                                   "--virtual-store-dir", pnpm_virtual_store],
                    cwd=sources / "js", environment=pnpm_environment)
            execute("js", ["pnpm", "--ignore-pnpmfile", "--filter", "event-store-adapter-js", "build"],
                    cwd=sources / "js", environment=pnpm_environment)
            execute("js-inputs", ["node", HERE / "drivers/js/runtime-inputs.cjs", "--record",
                                  sources / "js/packages/library", output / "js-runtime-inputs.json"], environment=pnpm_environment)
        if selected("go"):
            execute("go-inputs", ["go", "list", "-m", "-json", "all"], cwd=go, environment=go_environment)
        classpath = ((jvm / "classpath.txt").read_text() if selected("jvm")
                     else previous_inputs["jvm_classpath_inputs"]["classpath"])
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
                  "jvm_classpath_inputs": jvm_classpath_inputs(classpath), "cargo_config_inputs": cargo_inputs,
                  "cargo_inherited_config_inputs": cargo_inherited_inputs, "cargo_metadata_inputs": cargo_metadata_inputs,
                  "gradle_init_inputs": gradle_inputs, "go_build_environment": go_environment,
                  "cargo_build_environment": cargo_environment, "pnpm_hook_settings": pnpm_inputs,
                  "pnpm_virtual_store_dir": pnpm_virtual_store, "drivers": drivers}
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
